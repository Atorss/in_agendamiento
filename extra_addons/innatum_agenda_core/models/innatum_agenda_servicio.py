# -*- coding: utf-8 -*-

import re

from odoo import models, fields, api


class InnatumAgendaServicio(models.Model):
    """Servicios del tenant.

    Cada tenant (res.company) administra sus PROPIOS servicios: los crea,
    edita y elimina sin depender de Innatum. El aislamiento es por
    `company_id` (record rule multi-company). El código es único dentro de
    la empresa y se autogenera desde el nombre si se deja vacío.

    Campos de duración y operadores se usan en el modo de agenda "directa"
    (on-demand): la duración del turno sale del servicio y los operadores
    definen quién puede realizarlo.
    """
    _name = 'innatum.agenda.servicio'
    _description = 'Servicio'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(
        string='Código', copy=False,
        help='Identificador corto único dentro de la empresa (ej. CONTROL). '
             'Si se deja vacío se autogenera desde el nombre.')
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)
    color = fields.Integer(
        string='Color',
        help='Color con el que se muestran en los calendarios los turnos de '
             'este servicio. Se elige de la paleta estándar.',
    )
    image_1920 = fields.Image(
        string='Imagen',
        max_width=1920,
        max_height=1920,
        help='Imagen opcional del servicio. Si se define, el sitio público '
             'la muestra en la tarjeta del servicio; si no, se muestra solo '
             'el nombre.',
    )

    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, index=True,
        default=lambda self: self.env.company,
        help='Tenant dueño del servicio. Cada empresa administra los suyos.',
    )

    # --- Modo de agenda "directa": duración por servicio ---
    duracion = fields.Float(
        string='Duración (min)', default=30.0,
        help='Duración estándar del servicio en minutos. En modo de agenda '
             'Directa define cuánto dura el turno al agendar.',
    )
    duracion_variable = fields.Boolean(
        string='Duración variable',
        help='Si el servicio puede durar distinto cada vez (ej. cirugías). '
             'El operador ajusta la duración al agendar, entre el mín y el máx.',
    )
    duracion_min = fields.Float(string='Duración mín (min)')
    duracion_max = fields.Float(string='Duración máx (min)')

    publicar_web = fields.Boolean(
        string='Ofrecer online', default=True,
        help='Si está activo, el servicio se ofrece en los canales públicos '
             '(sitio web, chatbot, WhatsApp).',
    )

    operador_ids = fields.Many2many(
        'hr.employee',
        'innatum_agenda_employee_servicio_rel',
        'servicio_id', 'employee_id',
        string='Operadores que lo realizan',
        domain="[('company_id', '=', company_id)]",
        help='Profesionales del tenant que pueden realizar este servicio. '
             'Es el inverso de "Servicios que atiende" en la ficha del '
             'empleado: editar cualquiera de los dos lados actualiza el otro.',
    )

    _sql_constraints = [
        ('code_company_unique', 'unique(code, company_id)',
         'El código del servicio debe ser único dentro de la empresa.'),
    ]

    # ------------------------------------------------------------------
    # Autogeneración de código
    # ------------------------------------------------------------------

    @api.model
    def _slugify_code(self, name):
        base = re.sub(r'[^a-z0-9]+', '_', (name or '').strip().lower()).strip('_')
        return (base[:20] or 'serv').upper()

    @api.model
    def _next_code(self, name, company_id):
        base = self._slugify_code(name)
        code = base
        n = 1
        while self.sudo().search_count([
            ('code', '=', code), ('company_id', '=', company_id),
        ]):
            n += 1
            code = '%s_%d' % (base, n)
        return code

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                company_id = vals.get('company_id') or self.env.company.id
                vals['code'] = self._next_code(vals.get('name'), company_id)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Filtro por rol en el selector de servicios
    # ------------------------------------------------------------------

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """Filtra por el perfil del usuario cuando se solicita explícitamente
        con el contexto `servicios_por_rol` (selector de la planificación).

        - Administrador del tenant: ve todos los servicios de su compañía
          (el acceso ya está acotado por la record rule de company_id).
        - Operador / Usuario: solo los servicios asignados en su ficha de
          personal (hr.employee.servicio_ids).
        """
        if self.env.context.get('servicios_por_rol') and not self.env.su:
            is_admin = self.env.user.has_group(
                'innatum_agenda_core.innatum_agenda_group_admin')
            if not is_admin:
                emp = self.env['hr.employee'].sudo().search(
                    [('user_id', '=', self.env.uid)], limit=1)
                domain = list(domain or []) + [
                    ('id', 'in', emp.servicio_ids.ids)]
        return super()._search(domain, offset=offset, limit=limit, order=order)
