# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

import pytz

from odoo import models, fields, api
from odoo.exceptions import ValidationError


DAY_FIELDS = [
    (0, 'lunes', 'Lun'),
    (1, 'martes', 'Mar'),
    (2, 'miercoles', 'Mié'),
    (3, 'jueves', 'Jue'),
    (4, 'viernes', 'Vie'),
    (5, 'sabado', 'Sáb'),
    (6, 'domingo', 'Dom'),
]

DAY_FIELDS_LABELS = [(weekday, label) for weekday, _field, label in DAY_FIELDS]


class InnatumAgendaConfig(models.Model):
    _name = 'innatum.agenda.config'
    _description = 'Planificación de Horario'
    _inherit = ['mail.thread']
    _order = 'fecha_desde desc'
    _turno_model = 'innatum.agenda.turno'

    name = fields.Char(
        string='Nombre', compute='_compute_name', store=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Empresa',
        related='professional_id.company_id', store=True, readonly=True,
        help='Empresa del profesional. Se hereda automáticamente.',
    )
    servicio_ids = fields.Many2many(
        'innatum.agenda.servicio',
        'innatum_agenda_config_servicio_rel',
        'config_id', 'servicio_id',
        string='Servicios', tracking=True,
        help='Servicios que se ofrecen en estos horarios. Si se eligen '
             'varios, cada turno generado podrá ser para cualquiera de '
             'ellos — el cliente elige al reservar.',
    )
    professional_id = fields.Many2one(
        'hr.employee', string='Profesional', required=True, tracking=True,
        default=lambda self: self._default_professional_id(),
    )
    is_usuario_only = fields.Boolean(
        compute='_compute_is_usuario_only',
        default=lambda self: self._is_usuario_only_user(),
        help='True si el usuario logueado solo tiene el rol Usuario '
             '(sin Operador ni Administrador).',
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

    @api.depends_context('uid')
    def _compute_is_usuario_only(self):
        only_user = self._is_usuario_only_user()
        for rec in self:
            rec.is_usuario_only = only_user
    fecha_desde = fields.Date(
        string='Desde', required=True, tracking=True,
    )
    fecha_hasta = fields.Date(
        string='Hasta', required=True, tracking=True,
    )
    duracion_turno = fields.Float(
        string='Duración Turno (min)', required=True, default=30.0,
        help='Duración de cada turno en minutos',
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('approved', 'Aprobado'),
    ], string='Estado', default='draft', required=True, tracking=True)
    line_ids = fields.One2many(
        'innatum.agenda.config.line', 'config_id',
        string='Horarios por Día',
    )
    turno_ids = fields.One2many(
        'innatum.agenda.turno', 'config_id', string='Turnos',
    )
    turno_count = fields.Integer(
        string='Turnos', compute='_compute_turno_count',
    )
    turno_available_count = fields.Integer(
        string='Disponibles', compute='_compute_turno_count',
    )

    @api.depends('professional_id', 'fecha_desde', 'fecha_hasta')
    def _compute_name(self):
        for rec in self:
            if rec.professional_id and rec.fecha_desde and rec.fecha_hasta:
                rec.name = '%s — %s al %s' % (
                    rec.professional_id.name,
                    rec.fecha_desde.strftime('%d/%m/%Y'),
                    rec.fecha_hasta.strftime('%d/%m/%Y'),
                )
            else:
                rec.name = 'Nueva Planificación'

    @api.depends('turno_ids', 'turno_ids.state')
    def _compute_turno_count(self):
        for rec in self:
            turnos = rec.turno_ids.filtered(lambda t: t.state != 'cancelled')
            rec.turno_count = len(turnos)
            rec.turno_available_count = len(turnos.filtered(lambda t: t.state == 'available'))

    @api.onchange('professional_id')
    def _onchange_professional_servicios(self):
        """La planificación toma por defecto los servicios que atiende el
        profesional. El usuario puede ajustarlos después."""
        if self.professional_id and self.professional_id.servicio_ids:
            self.servicio_ids = self.professional_id.servicio_ids

    @api.constrains('servicio_ids', 'professional_id')
    def _check_servicios_habilitados_para_tenant(self):
        """Solo se pueden usar servicios habilitados por Innatum para
        la company del tenant (servicio.company_ids contiene la company
        del professional).
        """
        for rec in self:
            if not rec.professional_id or not rec.servicio_ids:
                continue
            company = rec.professional_id.company_id
            if not company:
                continue
            no_habilitados = rec.servicio_ids.filtered(
                lambda s: company not in s.company_ids
            )
            if no_habilitados:
                nombres = ', '.join(no_habilitados.mapped('name'))
                raise ValidationError(
                    f'Los siguientes servicios no están habilitados para '
                    f'la empresa "{company.name}": {nombres}.\n\n'
                    f'Contacta a Innatum para habilitarlos.'
                )

    @api.constrains('fecha_desde', 'fecha_hasta')
    def _check_fechas(self):
        for rec in self:
            if rec.fecha_hasta < rec.fecha_desde:
                raise ValidationError('La fecha "Hasta" debe ser mayor o igual a "Desde".')

    @api.constrains('professional_id', 'fecha_desde', 'fecha_hasta',
                    'servicio_ids', 'line_ids',
                    'line_ids.hora_inicio', 'line_ids.hora_fin',
                    'line_ids.lunes', 'line_ids.martes', 'line_ids.miercoles',
                    'line_ids.jueves', 'line_ids.viernes', 'line_ids.sabado',
                    'line_ids.domingo')
    def _check_no_overlap_other_configs(self):
        """Rechaza planificaciones del mismo empleado que se solapen con
        otra existente cuando coincidan: rango de fechas + al menos un
        servicio + alguna franja (día de la semana + hora) compartida."""
        for rec in self:
            if not (rec.professional_id and rec.fecha_desde and rec.fecha_hasta):
                continue
            others = self.search([
                ('id', '!=', rec.id),
                ('professional_id', '=', rec.professional_id.id),
                ('fecha_desde', '<=', rec.fecha_hasta),
                ('fecha_hasta', '>=', rec.fecha_desde),
            ])
            for other in others:
                shared_services = rec.servicio_ids & other.servicio_ids
                if not shared_services:
                    continue
                for line_a in rec.line_ids:
                    dias_a = set(line_a._get_dias_activos())
                    if not dias_a:
                        continue
                    for line_b in other.line_ids:
                        dias_comunes = dias_a & set(line_b._get_dias_activos())
                        if not dias_comunes:
                            continue
                        if line_a.hora_inicio < line_b.hora_fin \
                                and line_a.hora_fin > line_b.hora_inicio:
                            dias_label = ', '.join(
                                dict(DAY_FIELDS_LABELS)[d]
                                for d in sorted(dias_comunes)
                            )
                            raise ValidationError(
                                'Solapamiento con la planificación "%s" '
                                '(del %s al %s) para el profesional %s.\n'
                                'Servicio(s) en común: %s.\n'
                                'Día(s) y franja: %s, '
                                '%02d:%02d-%02d:%02d vs %02d:%02d-%02d:%02d.' % (
                                    other.name or other.display_name,
                                    other.fecha_desde.strftime('%d/%m/%Y'),
                                    other.fecha_hasta.strftime('%d/%m/%Y'),
                                    rec.professional_id.name,
                                    ', '.join(shared_services.mapped('name')),
                                    dias_label,
                                    int(line_a.hora_inicio),
                                    int((line_a.hora_inicio % 1) * 60),
                                    int(line_a.hora_fin),
                                    int((line_a.hora_fin % 1) * 60),
                                    int(line_b.hora_inicio),
                                    int((line_b.hora_inicio % 1) * 60),
                                    int(line_b.hora_fin),
                                    int((line_b.hora_fin % 1) * 60),
                                )
                            )

    def action_approve(self):
        """Aprueba la planificación y genera los turnos."""
        for rec in self:
            if not rec.line_ids:
                raise ValidationError('Debe configurar al menos un horario de atención.')
            rec.state = 'approved'
            rec._generar_turnos()

    def action_draft(self):
        """Vuelve a borrador y elimina turnos disponibles."""
        for rec in self:
            turnos_disponibles = rec.turno_ids.filtered(
                lambda t: t.state == 'available'
            )
            turnos_disponibles.unlink()
            rec.state = 'draft'

    def _float_to_time(self, float_hour):
        hours = int(float_hour)
        minutes = int((float_hour - hours) * 60)
        return hours, minutes

    def _generar_turnos(self):
        """Genera turnos basado en las líneas de horario y el rango de fechas.
        Para el día en curso, omite los slots cuyo inicio ya pasó.
        """
        self.ensure_one()
        Turno = self.env[self._turno_model]
        # TZ: user que aprueba > admin del sistema > UTC.
        # En "1 BD = 1 país" el admin tiene el TZ correcto seteado al crear
        # la BD; cualquier user del tenant también tendrá su propio TZ
        # configurado en preferencias.
        if self.env.user.tz:
            tz_name = self.env.user.tz
        else:
            # sudo: Public User del tenant no puede leer res.users del admin.
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            tz_name = (admin and admin.sudo().tz) or 'UTC'
        user_tz = pytz.timezone(tz_name)
        duracion_min = int(self.duracion_turno)
        now_utc = fields.Datetime.now()

        to_delete = self.turno_ids.filtered(
            lambda t: t.state == 'available'
        )
        to_delete.unlink()

        lineas_por_dia = {}
        for line in self.line_ids:
            for weekday in line._get_dias_activos():
                lineas_por_dia.setdefault(weekday, []).append(line)

        existing_starts = set(self.turno_ids.mapped('date_start'))

        vals_list = []
        current_date = self.fecha_desde
        while current_date <= self.fecha_hasta:
            for line in lineas_por_dia.get(current_date.weekday(), []):
                h_inicio, m_inicio = self._float_to_time(line.hora_inicio)
                h_fin, m_fin = self._float_to_time(line.hora_fin)

                slot_start_local = user_tz.localize(datetime(
                    current_date.year, current_date.month, current_date.day,
                    h_inicio, m_inicio,
                ))
                day_end_local = user_tz.localize(datetime(
                    current_date.year, current_date.month, current_date.day,
                    h_fin, m_fin,
                ))

                slot_start = slot_start_local.astimezone(pytz.utc).replace(tzinfo=None)
                day_end = day_end_local.astimezone(pytz.utc).replace(tzinfo=None)

                while slot_start + timedelta(minutes=duracion_min) <= day_end:
                    slot_end = slot_start + timedelta(minutes=duracion_min)
                    if slot_start >= now_utc and slot_start not in existing_starts:
                        vals_list.append(self._prepare_turno_vals(slot_start))
                    slot_start = slot_end
            current_date += timedelta(days=1)

        if vals_list:
            Turno.create(vals_list)

    def _prepare_turno_vals(self, date_start):
        """Prepara vals para crear un turno. Override en módulos hijos.

        Cada turno hereda los servicios de la config como opciones (M2M).
        Si la config tiene un único servicio, también se preselecciona
        servicio_id para mantener compatibilidad y simplificar el flujo.
        """
        servicio_ids = self.servicio_ids.ids
        vals = {
            'professional_id': self.professional_id.id,
            'config_id': self.id,
            'servicio_ids': [(6, 0, servicio_ids)] if servicio_ids else False,
            'date_start': date_start,
            'state': 'available',
        }
        if len(servicio_ids) == 1:
            vals['servicio_id'] = servicio_ids[0]
        return vals

    def _get_turno_action(self, domain, name):
        """Retorna action para ver turnos filtrados."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': self._turno_model,
            'view_mode': 'list,calendar,form',
            'domain': domain,
            'context': {
                'default_professional_id': self.professional_id.id,
                'default_config_id': self.id,
            },
        }

    def action_view_turnos(self):
        self.ensure_one()
        return self._get_turno_action(
            [('config_id', '=', self.id), ('state', '!=', 'cancelled')],
            'Turnos — %s' % self.name,
        )

    def action_view_turnos_available(self):
        self.ensure_one()
        return self._get_turno_action(
            [('config_id', '=', self.id), ('state', '=', 'available')],
            'Disponibles — %s' % self.name,
        )


class InnatumAgendaConfigLine(models.Model):
    _name = 'innatum.agenda.config.line'
    _description = 'Línea de Horario'
    _order = 'hora_inicio'

    config_id = fields.Many2one(
        'innatum.agenda.config', string='Configuración',
        required=True, ondelete='cascade',
    )
    lunes = fields.Boolean(string='Lun')
    martes = fields.Boolean(string='Mar')
    miercoles = fields.Boolean(string='Mié')
    jueves = fields.Boolean(string='Jue')
    viernes = fields.Boolean(string='Vie')
    sabado = fields.Boolean(string='Sáb')
    domingo = fields.Boolean(string='Dom')
    hora_inicio = fields.Float(
        string='Hora Inicio', required=True, default=8.0,
    )
    hora_fin = fields.Float(
        string='Hora Fin', required=True, default=17.0,
    )
    dias_display = fields.Char(
        string='Días', compute='_compute_dias_display',
    )
    turnos_por_dia = fields.Integer(
        string='Turnos/Día', compute='_compute_turnos_por_dia',
    )

    def _get_dias_activos(self):
        self.ensure_one()
        dias = []
        for weekday, field_name, _label in DAY_FIELDS:
            if self[field_name]:
                dias.append(weekday)
        return dias

    @api.depends('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')
    def _compute_dias_display(self):
        for line in self:
            nombres = []
            for _weekday, field_name, label in DAY_FIELDS:
                if line[field_name]:
                    nombres.append(label)
            line.dias_display = ', '.join(nombres) if nombres else ''

    @api.depends('hora_inicio', 'hora_fin', 'config_id.duracion_turno')
    def _compute_turnos_por_dia(self):
        for line in self:
            duracion = line.config_id.duracion_turno
            if duracion > 0:
                horas = line.hora_fin - line.hora_inicio
                line.turnos_por_dia = int((horas * 60) / duracion)
            else:
                line.turnos_por_dia = 0

    @api.constrains('hora_inicio', 'hora_fin')
    def _check_horario(self):
        for line in self:
            if line.hora_fin <= line.hora_inicio:
                raise ValidationError(
                    'La hora fin debe ser mayor a la hora inicio.'
                )

    @api.constrains('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')
    def _check_al_menos_un_dia(self):
        for line in self:
            if not line._get_dias_activos():
                raise ValidationError('Debe seleccionar al menos un día.')

    @api.constrains('hora_inicio', 'hora_fin', 'lunes', 'martes', 'miercoles',
                     'jueves', 'viernes', 'sabado', 'domingo', 'config_id')
    def _check_no_overlap(self):
        for line in self:
            dias = set(line._get_dias_activos())
            for other in (line.config_id.line_ids - line):
                dias_comunes = dias & set(other._get_dias_activos())
                if dias_comunes and line.hora_inicio < other.hora_fin and line.hora_fin > other.hora_inicio:
                    nombres = [dict(DAY_FIELDS_LABELS)[d] for d in sorted(dias_comunes)]
                    raise ValidationError(
                        'Solapamiento de horarios en: %s '
                        '(%02d:%02d-%02d:%02d vs %02d:%02d-%02d:%02d).' % (
                            ', '.join(nombres),
                            int(line.hora_inicio), int((line.hora_inicio % 1) * 60),
                            int(line.hora_fin), int((line.hora_fin % 1) * 60),
                            int(other.hora_inicio), int((other.hora_inicio % 1) * 60),
                            int(other.hora_fin), int((other.hora_fin % 1) * 60),
                        )
                    )

    def unlink(self):
        """Al eliminar una línea de horario, eliminar los turnos disponibles."""
        for line in self:
            if line.config_id and line.config_id.state == 'approved':
                dias_activos = set(line._get_dias_activos())
                turnos_a_eliminar = line.config_id.turno_ids.filtered(
                    lambda t: (
                        t.state == 'available'
                        and t.date_start
                        and t.date_start.weekday() in dias_activos
                    )
                )
                turnos_a_eliminar.unlink()
        return super().unlink()
