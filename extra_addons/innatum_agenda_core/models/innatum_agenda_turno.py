# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InnatumAgendaTurno(models.Model):
    _name = 'innatum.agenda.turno'
    _description = 'Turno'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start asc'

    name = fields.Char(
        string='Referencia', required=True, copy=False,
        readonly=True, default='Nuevo',
    )
    company_id = fields.Many2one(
        'res.company', string='Empresa',
        related='professional_id.company_id', store=True, readonly=True,
        help='Empresa del profesional. Se hereda automáticamente.',
    )
    professional_id = fields.Many2one(
        'hr.employee', string='Profesional', required=True, tracking=True,
        default=lambda self: self._default_professional_id(),
    )
    servicio_id = fields.Many2one(
        'innatum.agenda.servicio', string='Servicio', tracking=True,
        store=True,
        help='Servicio elegido al reservar. Si la planificación ofrece '
             'varios servicios, queda vacío hasta que el cliente reserve.',
    )
    servicio_ids = fields.Many2many(
        'innatum.agenda.servicio',
        'innatum_agenda_turno_servicio_rel',
        'turno_id', 'servicio_id',
        string='Servicios disponibles',
        help='Servicios que se pueden ofrecer en este horario, heredados '
             'de la planificación.',
    )
    servicio_count = fields.Integer(
        compute='_compute_servicio_count',
        help='Cantidad de servicios disponibles. Usado en vistas porque '
             'el evaluador de expresiones no expone len().',
    )
    config_id = fields.Many2one(
        'innatum.agenda.config', string='Planificación',
    )

    # ------------------------------------------------------------------
    # Restricciones por rol del usuario logueado
    # ------------------------------------------------------------------
    is_usuario_only = fields.Boolean(
        compute='_compute_is_usuario_only',
        default=lambda self: self._is_usuario_only_user(),
        help='True si el usuario logueado solo tiene el rol Usuario '
             '(sin Operador ni Administrador).',
    )
    domain_servicio_ids = fields.Many2many(
        'innatum.agenda.servicio',
        compute='_compute_domain_servicio_ids',
        default=lambda self: self._default_domain_servicio_ids(),
        help='Servicios visibles para el usuario logueado en el campo '
             'servicio_id. Se restringen a los servicios donde tiene '
             'planificación si es solo Usuario.',
    )

    @api.model
    def _is_usuario_only_user(self):
        """Devuelve True si el usuario logueado pertenece SOLO al grupo
        Usuario de Agenda (no es Operador ni Administrador)."""
        user = self.env.user
        is_user = user.has_group('innatum_agenda_core.innatum_agenda_group_user')
        is_op = user.has_group('innatum_agenda_core.innatum_agenda_group_operator')
        is_admin = user.has_group('innatum_agenda_core.innatum_agenda_group_admin')
        return is_user and not is_op and not is_admin

    @api.model
    def _default_professional_id(self):
        """Si el usuario logueado es solo Usuario de Agenda, devuelve su
        empleado vinculado para que el campo se prellene y quede readonly."""
        if not self._is_usuario_only_user():
            return False
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
        ], limit=1)
        return employee.id if employee else False

    @api.model
    def _default_domain_servicio_ids(self):
        """Lista inicial de servicios visibles según el rol del usuario."""
        Servicio = self.env['innatum.agenda.servicio']
        if not self._is_usuario_only_user():
            return [(6, 0, Servicio.search([]).ids)]
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
        ], limit=1)
        if not employee:
            return [(6, 0, [])]
        servicios = self.env['innatum.agenda.config'].sudo().search([
            ('professional_id', '=', employee.id),
        ]).mapped('servicio_ids')
        return [(6, 0, servicios.ids)]

    @api.depends_context('uid')
    def _compute_is_usuario_only(self):
        only_user = self._is_usuario_only_user()
        for rec in self:
            rec.is_usuario_only = only_user

    @api.depends('servicio_ids')
    def _compute_servicio_count(self):
        for rec in self:
            rec.servicio_count = len(rec.servicio_ids)

    @api.depends_context('uid')
    def _compute_domain_servicio_ids(self):
        """Restringe los servicios disponibles según el rol del usuario:
        - Solo Usuario: únicamente servicios donde tiene planificación.
        - Operador / Administrador: todos los servicios.
        """
        Servicio = self.env['innatum.agenda.servicio']
        if self._is_usuario_only_user():
            employee = self.env['hr.employee'].sudo().search([
                ('user_id', '=', self.env.uid),
            ], limit=1)
            if employee:
                servicios = self.env['innatum.agenda.config'].sudo().search([
                    ('professional_id', '=', employee.id),
                ]).mapped('servicio_ids')
            else:
                servicios = Servicio.browse()
        else:
            servicios = Servicio.search([])
        for rec in self:
            rec.domain_servicio_ids = [(6, 0, servicios.ids)]
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', tracking=True,
    )
    client_phone = fields.Char(
        related='partner_id.mobile', string='Celular', readonly=True,
    )
    client_email = fields.Char(
        related='partner_id.email', string='Email', readonly=True,
    )
    date_start = fields.Datetime(
        string='Fecha y Hora', required=True, tracking=True,
    )
    date_end = fields.Datetime(
        string='Fin', compute='_compute_date_end', store=True,
    )
    duration = fields.Float(
        string='Duración (min)', compute='_compute_duration', store=True,
    )
    state = fields.Selection([
        ('available', 'Disponible'),
        ('reserved', 'Reservado'),
        ('confirmed', 'Confirmado'),
        ('done', 'Finalizado'),
        ('cancelled', 'Cancelado'),
    ], string='Estado', default='available', required=True, tracking=True)
    notes = fields.Text(string='Notas')
    publicar = fields.Boolean(
        string='Publicar', default=True,
        help='Si está activo, el turno será visible en el portal web.',
    )

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains('state', 'servicio_id', 'servicio_ids')
    def _check_servicio_required_when_reserved(self):
        for rec in self:
            if rec.state in ('reserved', 'confirmed', 'done') and not rec.servicio_id:
                raise ValidationError(
                    'Debes seleccionar un servicio para reservar este turno.'
                )
            # Si hay opciones definidas, el servicio elegido debe ser una de ellas
            if rec.servicio_id and rec.servicio_ids and \
                    rec.servicio_id not in rec.servicio_ids:
                raise ValidationError(
                    f'El servicio "{rec.servicio_id.name}" no está entre las '
                    f'opciones disponibles de este horario.'
                )

    @api.constrains('partner_id')
    def _check_partner_same_company(self):
        """Coherencia multi-tenant: el cliente del turno debe ser del mismo
        tenant que el turno. Defensa en profundidad: el flujo público ya crea
        el partner en la company del website, pero esto bloquea asignaciones
        cruzadas por backend/RPC."""
        for rec in self:
            p = rec.partner_id
            if (p and p.company_id and rec.company_id
                    and p.company_id != rec.company_id):
                raise ValidationError(
                    'El cliente seleccionado pertenece a otra empresa. '
                    'No se puede reservar este turno a su nombre.'
                )

    @api.constrains('date_start')
    def _check_date_start_future(self):
        for rec in self:
            if rec.date_start and rec.date_start < fields.Datetime.now():
                if self.env.context.get('allow_past_dates'):
                    continue
                raise ValidationError(
                    "No se puede crear un turno en una fecha pasada."
                )

    @api.constrains('date_start', 'date_end', 'professional_id')
    def _check_no_overlap(self):
        for rec in self:
            if not rec.date_start or not rec.date_end or not rec.professional_id:
                continue
            if rec.state == 'cancelled':
                continue
            overlap = self.search([
                ('id', '!=', rec.id),
                ('professional_id', '=', rec.professional_id.id),
                ('state', '!=', 'cancelled'),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ], limit=1)
            if overlap:
                raise ValidationError(
                    f"El turno se cruza con otro del mismo profesional.\n\n"
                    f"Turno existente: {overlap.name} "
                    f"({overlap.date_start.strftime('%d/%m/%Y %H:%M')} - "
                    f"{overlap.date_end.strftime('%H:%M')})"
                )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends('date_start', 'config_id.duracion_turno')
    def _compute_date_end(self):
        for rec in self:
            if rec.date_start:
                duracion = rec.config_id.duracion_turno if rec.config_id else 30
                rec.date_end = fields.Datetime.add(rec.date_start, minutes=int(duracion))
            else:
                rec.date_end = False

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for rec in self:
            if rec.date_start and rec.date_end:
                delta = rec.date_end - rec.date_start
                rec.duration = delta.total_seconds() / 60.0
            else:
                rec.duration = 0.0

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if not res.get('config_id'):
            now = fields.Datetime.now()
            if not res.get('date_start'):
                res['date_start'] = fields.Datetime.to_string(now)
            else:
                date_start = fields.Datetime.to_datetime(res['date_start'])
                if date_start.hour == 7 and date_start.minute == 0:
                    date_start = date_start.replace(hour=now.hour, minute=now.minute)
                    res['date_start'] = fields.Datetime.to_string(date_start)
            date_start = fields.Datetime.to_datetime(res['date_start'])
            res['date_end'] = fields.Datetime.to_string(
                fields.Datetime.add(date_start, minutes=30)
            )
        return res

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = self._generate_turno_name(vals)
        return super().create(vals_list)

    def _generate_turno_name(self, vals):
        """Genera referencia: TRN/SERVICIO/AÑO-MES/SECUENCIAL.
        Si hay un servicio elegido (servicio_id), usa ese código.
        Si no, deriva del primer servicio en servicio_ids.
        Si la planificación ofrece varios servicios, usa el código del primero.
        """
        Servicio = self.env['innatum.agenda.servicio']
        code = 'GEN'
        servicio_id = vals.get('servicio_id')
        if servicio_id:
            servicio = Servicio.browse(servicio_id)
            if servicio.exists() and servicio.code:
                code = servicio.code
        else:
            servicio_ids_cmd = vals.get('servicio_ids') or []
            servicio_ids = []
            for cmd in servicio_ids_cmd:
                if isinstance(cmd, (list, tuple)) and len(cmd) >= 3 and cmd[0] == 6:
                    servicio_ids = list(cmd[2] or [])
                    break
            if servicio_ids:
                primer = Servicio.browse(servicio_ids[0])
                if primer.exists() and primer.code:
                    code = primer.code

        date_start = vals.get('date_start')
        if date_start:
            if isinstance(date_start, str):
                date_start = fields.Datetime.from_string(date_start)
            year_month = date_start.strftime('%Y-%m')
        else:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y-%m')

        seq_code = 'innatum.agenda.turno.%s.%s' % (code.lower(), year_month)
        seq = self.env['ir.sequence'].sudo().search([('code', '=', seq_code)], limit=1)
        if not seq:
            seq = self.env['ir.sequence'].sudo().create({
                'name': 'Turno %s %s' % (code, year_month),
                'code': seq_code,
                'prefix': 'TRN/%s/%s/' % (code, year_month),
                'padding': 4,
                'company_id': False,
            })
        return seq.next_by_id() or 'Nuevo'

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_reserve(self):
        for rec in self:
            rec.state = 'reserved'

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_free(self):
        """Liberar turno: quitar cliente y volver a disponible.
        Si el turno permitía varios servicios (servicio_ids con >1), también
        limpia el servicio elegido para que el próximo cliente pueda escoger.
        Si solo hay una opción, mantiene servicio_id seteado.
        """
        for rec in self:
            vals = {
                'state': 'available',
                'partner_id': False,
            }
            if len(rec.servicio_ids) > 1:
                vals['servicio_id'] = False
            rec.write(vals)
