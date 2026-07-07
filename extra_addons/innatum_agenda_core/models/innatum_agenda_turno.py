# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

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
    servicios_profesional_ids = fields.Many2many(
        'innatum.agenda.servicio',
        compute='_compute_servicios_profesional_ids',
        string='Servicios del profesional',
        help='Servicios que el profesional seleccionado tiene registrados '
             '(los que atiende). Restringe el domain de "Servicio elegido": '
             'cada profesional solo puede brindar sus servicios registrados.',
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
        """Prellena el profesional del turno con el empleado del usuario
        logueado (si tiene uno), sea cual sea su rol. Comodidad: al crear un
        turno normalmente uno se lo agenda a sí mismo.
        - Rol 'solo Usuario': queda readonly (no puede cambiarlo).
        - Operador / Administrador: pueden elegir a otro profesional.
        La acción Derivaciones fuerza default_professional_id=False por
        contexto para que una derivación nazca sin profesional."""
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
        ], limit=1)
        return employee.id if employee else False

    @api.model
    def get_business_hours_usuario(self, turno_id=None):
        """Horario laboral en el formato `businessHours` de FullCalendar, para
        sombrear en el calendario las franjas fuera de la jornada (fondo gris
        tenue). Lo consume la extensión JS del calendario.

        - Si se pasa `turno_id` (selector de horario de un turno concreto), usa
          el horario del PROFESIONAL DE ESE TURNO, para que el fondo sea
          coherente con los bloques ocupados que se muestran.
        - Si no, usa el empleado del usuario logueado (calendarios de turnos y
          bloqueos).

        Devuelve lista de dicts {daysOfWeek:[...], startTime:'HH:MM',
        endTime:'HH:MM'}. Vacío si no hay empleado o calendario. El almuerzo
        (day_period='lunch') se excluye para que quede sombreado."""
        emp = False
        if turno_id:
            turno = self.browse(turno_id).exists()
            emp = turno.professional_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.env.uid)], limit=1)
        if not emp:
            return []
        cal = emp.resource_calendar_id or emp.company_id.resource_calendar_id
        if not cal:
            return []

        def _hhmm(f):
            f = max(0.0, min(24.0, f or 0.0))
            h = int(f)
            m = int(round((f - h) * 60))
            if m == 60:
                h, m = h + 1, 0
            return '%02d:%02d' % (h, m)

        out = []
        for att in cal.sudo().attendance_ids:
            if att.day_period == 'lunch':
                continue
            # Odoo dayofweek: '0'=Lunes ... '6'=Domingo.
            # FullCalendar daysOfWeek: 0=Domingo ... 6=Sábado.
            fc_day = (int(att.dayofweek) + 1) % 7
            out.append({
                'daysOfWeek': [fc_day],
                'startTime': _hhmm(att.hour_from),
                'endTime': _hhmm(att.hour_to),
            })
        return out

    @api.model
    def _servicios_visibles_para_usuario(self, employee):
        """Servicios que un rol 'Usuario' puede elegir al crear un turno.

        Consciente del modo de agenda (dual-mode):
        - Directa: no hay planificaciones; los servicios vienen de los que el
          empleado tiene asignados (employee.servicio_ids).
        - Planificada: como siempre, de las planificaciones del empleado
          (innatum.agenda.config.servicio_ids).
        """
        if not employee:
            return self.env['innatum.agenda.servicio'].browse()
        if employee.company_id.agenda_modo == 'directa':
            return employee.servicio_ids
        return self.env['innatum.agenda.config'].sudo().search([
            ('professional_id', '=', employee.id),
        ]).mapped('servicio_ids')

    @api.model
    def _default_domain_servicio_ids(self):
        """Lista inicial de servicios visibles según el rol del usuario."""
        Servicio = self.env['innatum.agenda.servicio']
        if not self._is_usuario_only_user():
            return [(6, 0, Servicio.search([]).ids)]
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
        ], limit=1)
        servicios = self._servicios_visibles_para_usuario(employee)
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

    @api.depends('professional_id', 'professional_id.servicio_ids')
    def _compute_servicios_profesional_ids(self):
        """Servicios que el profesional elegido tiene registrados. Es la
        fuente del domain de servicio_id: un profesional solo puede dar los
        servicios que atiende (employee.servicio_ids)."""
        for rec in self:
            rec.servicios_profesional_ids = rec.professional_id.servicio_ids

    @api.onchange('professional_id')
    def _onchange_professional_reset_servicio(self):
        """Al cambiar el profesional, si el servicio elegido no está entre los
        que ese profesional atiende, se limpia (obliga a re-elegir uno válido).
        Se respeta el domain de una planificación (servicio_ids) si existe."""
        for rec in self:
            if not rec.professional_id:
                continue
            permitidos = rec.servicio_ids or rec.professional_id.servicio_ids
            if rec.servicio_id and rec.servicio_id not in permitidos:
                rec.servicio_id = False

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
            servicios = self._servicios_visibles_para_usuario(employee)
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
        string='Fecha y Hora', tracking=True,
        help='En una derivación queda vacío hasta que se elige un horario '
             'propuesto; en ese momento el turno pasa al flujo normal.',
    )
    date_end = fields.Datetime(
        string='Fin', compute='_compute_date_end',
        inverse='_inverse_date_end', store=True, readonly=False,
        help='Se calcula por defecto según la duración del servicio, pero '
             'podés editarlo para alargar o acortar este turno en particular '
             '(ej. un servicio de 30 min que en este caso durará 45).',
    )
    duracion_override = fields.Float(
        string='Duración personalizada (min)',
        help='Si se define (>0) fija la duración del turno en minutos, '
             'ignorando la del servicio. Se completa automáticamente cuando '
             'editás la hora de fin, y se mantiene aunque muevas el inicio.',
    )
    duration = fields.Float(
        string='Duración (min)', compute='_compute_duration', store=True,
    )
    color = fields.Integer(
        string='Color', related='servicio_id.color', store=True, readonly=True,
        help='Color del turno en el calendario: el configurado en su servicio.',
    )
    state = fields.Selection([
        ('derivado', 'Derivación (por agendar)'),
        ('propuesto', 'Horarios propuestos'),
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
    # Derivación entre colaboradores (se maneja en este mismo modelo)
    # ------------------------------------------------------------------
    es_derivacion = fields.Boolean(
        string='Es derivación', default=False, copy=False,
        help='Marca los turnos originados por una derivación entre '
             'colaboradores. Se gestionan en el menú "Derivaciones".',
    )
    derivado_por_id = fields.Many2one(
        'hr.employee', string='Derivado por', copy=False, tracking=True,
        help='Colaborador que originó la derivación (quien deriva al cliente).',
    )
    motivo_derivacion = fields.Text(
        string='Motivo de la derivación', copy=False,
    )
    turno_origen_id = fields.Many2one(
        'innatum.agenda.turno', string='Turno de origen', copy=False,
        readonly=True,
        help='Turno desde el que se originó la derivación (si aplica).',
    )
    derivacion_ids = fields.One2many(
        'innatum.agenda.turno', 'turno_origen_id',
        string='Derivaciones generadas', copy=False,
        help='Derivaciones originadas desde este turno (su turno_origen_id '
             'apunta acá).',
    )
    tiene_derivacion = fields.Boolean(
        compute='_compute_tiene_derivacion',
        help='Verdadero si de este turno ya salió una derivación activa (no '
             'cancelada). Se usa para ocultar el botón "Derivar" una vez que '
             'la derivación ya se hizo.',
    )
    propuesta_ids = fields.One2many(
        'innatum.agenda.turno.propuesta', 'derivacion_id',
        string='Horarios propuestos', copy=False,
        domain=[('tipo', '=', 'propuesta')],
        help='Días y horas que el colaborador que atiende propone para el '
             'cliente. Al elegir uno, el turno pasa al flujo normal. Solo '
             'incluye las propuestas reales; los bloques "ocupado" del '
             'planificador NO forman parte de este one2many.',
    )
    propuesta_count = fields.Integer(compute='_compute_propuesta_count')

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

    @api.constrains('state', 'date_start')
    def _check_date_start_required(self):
        """Estados que aún NO exigen fecha:
        - derivado/propuesto: derivación por agendar.
        - available: un turno recién creado nace sin horario; se le asigna al
          elegirlo en el calendario. Recién al reservar/confirmar es obligatoria.
        - cancelled: una derivación (u otro turno) puede cancelarse antes de
          tener fecha asignada (ej. action_cancel() sobre una derivación
          'derivado'/'propuesto').
        """
        for rec in self:
            if rec.state not in ('derivado', 'propuesto', 'available',
                                  'cancelled') \
                    and not rec.date_start:
                raise ValidationError(
                    "El turno necesita una fecha y hora."
                )

    @api.constrains('es_derivacion', 'professional_id', 'derivado_por_id')
    def _check_derivacion_distintos(self):
        for rec in self:
            if rec.es_derivacion and rec.derivado_por_id \
                    and rec.professional_id == rec.derivado_por_id:
                raise ValidationError(
                    "No podés derivarte el cliente a vos mismo: elegí a otro "
                    "colaborador para que lo atienda."
                )

    # Margen de tolerancia para la validación de "fecha pasada". La fecha por
    # defecto de un turno nuevo es la hora actual; entre que se abre el
    # formulario y se guarda (p.ej. al pulsar "Elegir horario en calendario",
    # que guarda el registro antes de correr la acción) pasan segundos/minutos
    # y ese valor por defecto queda técnicamente "en el pasado". Este colchón
    # absorbe ese desfase sin permitir agendar realmente en el pasado.
    _TOLERANCIA_PASADO_MIN = 30

    @api.constrains('date_start')
    def _check_date_start_future(self):
        for rec in self:
            if not rec.date_start:
                continue
            limite = fields.Datetime.now() - timedelta(
                minutes=self._TOLERANCIA_PASADO_MIN)
            if rec.date_start < limite:
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
            if rec.state in ('cancelled', 'derivado', 'propuesto'):
                continue
            overlap = self.search([
                ('id', '!=', rec.id),
                ('professional_id', '=', rec.professional_id.id),
                ('state', 'not in', ('cancelled', 'derivado', 'propuesto')),
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

    @api.constrains('date_start', 'date_end', 'professional_id', 'state')
    def _check_no_overlap_bloqueo(self):
        """No permitir un turno que se cruce con un BLOQUEO del mismo
        profesional. Aplica a cualquier creación/edición del turno (backend,
        web, chatbot), no solo al flujo on-demand. Se usa sudo porque los
        bloqueos son personales (record rule por dueño) y el que agenda puede
        no ser el profesional bloqueado."""
        Bloqueo = self.env['innatum.agenda.bloqueo'].sudo()
        for rec in self:
            if not rec.date_start or not rec.date_end or not rec.professional_id:
                continue
            if rec.state == 'cancelled':
                continue
            bloqueo = Bloqueo.search([
                ('professional_id', '=', rec.professional_id.id),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ], limit=1)
            if bloqueo:
                raise ValidationError(
                    "El turno se cruza con un bloqueo del profesional.\n\n"
                    "Bloqueo: %s (%s - %s)" % (
                        bloqueo.motivo or 'Bloqueo',
                        bloqueo.date_start.strftime('%d/%m/%Y %H:%M'),
                        bloqueo.date_end.strftime('%H:%M'),
                    )
                )

    @staticmethod
    def _intervalo_cubierto(ini, fin, intervals):
        """True si [ini, fin] está totalmente contenido en la unión de
        `intervals` (lista de tuplas (inicio, fin)). Si hay un hueco no cubierto
        dentro del rango (p.ej. un fin de semana o fuera del horario), False."""
        cur = ini
        for s, e in sorted((s, e) for s, e in intervals if e > s):
            if s > cur:
                return False  # hueco no laborable dentro del turno
            if e > cur:
                cur = e
            if cur >= fin:
                return True
        return cur >= fin

    @api.constrains('date_start', 'date_end', 'professional_id', 'state')
    def _check_dentro_horario_laboral(self):
        """En modo 'directa', un turno debe caer dentro del horario de trabajo
        del profesional (su resource.calendar). Evita agendar fines de semana o
        fuera de hora cuando el profesional no labora en ese momento.

        Solo aplica en modo 'directa' (la disponibilidad se define por el
        calendario laboral). En 'planificada' los slots los define la
        planificación, no el calendario, así que no se valida acá. Si el
        profesional no tiene calendario/recurso configurado, no se puede
        determinar el horario y NO se bloquea (se omite)."""
        Avail = self.env['innatum.agenda.availability']
        for rec in self:
            if rec.state in ('cancelled', 'derivado', 'propuesto'):
                continue
            if not rec.date_start or not rec.date_end or not rec.professional_id:
                continue
            if rec.company_id.agenda_modo != 'directa':
                continue
            prof = rec.professional_id
            cal = prof.resource_calendar_id or prof.company_id.resource_calendar_id
            # Sin calendario/recurso no hay horario que validar: se omite.
            if not cal or not prof.resource_id:
                continue
            work = Avail._work_intervals(prof, rec.date_start, rec.date_end)
            if not self._intervalo_cubierto(rec.date_start, rec.date_end, work):
                raise ValidationError(_(
                    'El horario elegido está fuera del horario de trabajo de '
                    '%(prof)s. Elegí un horario dentro de su jornada laboral '
                    '(o ajustá su calendario si debe atender en ese momento).',
                    prof=prof.name))

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends('date_start', 'config_id.duracion_turno',
                 'servicio_id.duracion', 'duracion_override')
    def _compute_date_end(self):
        """Duración del turno por prioridad:
        1. duracion_override (>0) — modo directo, ajuste manual (cirugías).
        2. config.duracion_turno — modo planificada (sin cambios).
        3. servicio.duracion — modo directo, duración estándar del servicio.
        4. 30 min — fallback.
        """
        for rec in self:
            if not rec.date_start:
                rec.date_end = False
                continue
            if rec.duracion_override:
                mins = rec.duracion_override
            elif rec.config_id:
                mins = rec.config_id.duracion_turno or 30
            elif rec.servicio_id and rec.servicio_id.duracion:
                mins = rec.servicio_id.duracion
            else:
                mins = 30
            rec.date_end = fields.Datetime.add(rec.date_start, minutes=int(mins))

    def _inverse_date_end(self):
        """Al editar la hora de fin a mano, se guarda esa duración como
        'duracion_override' para que el turno conserve la duración elegida
        (y se respete aunque después se mueva la hora de inicio)."""
        for rec in self:
            if rec.date_start and rec.date_end:
                mins = (rec.date_end - rec.date_start).total_seconds() / 60.0
                rec.duracion_override = mins if mins > 0 else 0.0

    @api.onchange('servicio_id')
    def _onchange_servicio_reset_duracion(self):
        """Al cambiar el servicio, volver a la duración estándar del nuevo
        servicio (se descarta el ajuste manual previo). El usuario puede
        volver a editar la hora de fin si necesita extenderlo."""
        for rec in self:
            rec.duracion_override = 0.0

    @api.constrains('date_start', 'date_end', 'state')
    def _check_date_end_after_start(self):
        for rec in self:
            if rec.state in ('derivado', 'propuesto'):
                continue
            if rec.date_start and rec.date_end \
                    and rec.date_end <= rec.date_start:
                raise ValidationError(
                    'La hora de fin debe ser posterior a la de inicio.'
                )

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for rec in self:
            if rec.date_start and rec.date_end:
                delta = rec.date_end - rec.date_start
                rec.duration = delta.total_seconds() / 60.0
            else:
                rec.duration = 0.0

    @api.depends('propuesta_ids', 'propuesta_ids.tipo')
    def _compute_propuesta_count(self):
        for rec in self:
            rec.propuesta_count = len(rec.propuesta_ids.filtered(
                lambda p: p.tipo == 'propuesta'))

    @api.depends('derivacion_ids', 'derivacion_ids.state')
    def _compute_tiene_derivacion(self):
        for rec in self:
            rec.tiene_derivacion = bool(rec.derivacion_ids.filtered(
                lambda d: d.state != 'cancelled'))

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Una derivación aún no tiene fecha: no prellenar date_start/date_end.
        if self.env.context.get('default_state') == 'derivado':
            return res
        # Un turno nuevo NACE SIN horario (date_start/date_end vacíos): se le
        # asigna al pulsar "Elegir horario en calendario". Así el valor por
        # defecto (la hora actual) no dispara validaciones de cruce ni de fuera
        # de horario antes de que el usuario elija el horario real.
        # Excepción: si la fecha viene dada por contexto (p.ej. clic en un hueco
        # del calendario), se respeta; solo se ajusta el placeholder 7:00 de las
        # planificaciones a la hora actual.
        if not res.get('config_id') and res.get('date_start'):
            now = fields.Datetime.now()
            date_start = fields.Datetime.to_datetime(res['date_start'])
            if date_start.hour == 7 and date_start.minute == 0:
                date_start = date_start.replace(hour=now.hour, minute=now.minute)
                res['date_start'] = fields.Datetime.to_string(date_start)
        return res

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Una derivación 'por agendar' nace sin fecha (se fija al elegir un
            # horario propuesto). Fijar date_start en vals evita que
            # default_get lo prellene con la hora actual.
            if vals.get('state') == 'derivado' and not vals.get('date_start'):
                vals['date_start'] = False
            # En una derivación, registrar quién la originó (si no vino dado).
            if vals.get('es_derivacion') and not vals.get('derivado_por_id'):
                emp = self.env.user.employee_id
                if emp:
                    vals['derivado_por_id'] = emp.id
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
        # Al cancelar una derivación por agendar, limpiar su planificador.
        deriv = self.filtered(
            lambda t: t.es_derivacion and t.state in ('derivado', 'propuesto'))
        if deriv:
            self.env['innatum.agenda.turno.propuesta'].sudo().search(
                [('derivacion_id', 'in', deriv.ids)]).unlink()
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

    def action_derivar(self):
        """Abre el wizard de derivación: se elige el colaborador que atenderá
        y el servicio. Al confirmar se crea, en este mismo modelo, un turno
        'por agendar' (estado derivado) para que ese colaborador proponga los
        horarios."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_(
                'Asigná un cliente al turno antes de derivarlo.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Derivar cliente'),
            'res_model': 'innatum.agenda.turno.derivar.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_turno_id': self.id,
                'default_servicio_id': self.servicio_id.id,
            },
        }

    def action_ver_propuestas(self):
        """Atajo para abrir la derivación en su formulario dedicado."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'innatum.agenda.turno',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'innatum_agenda_core.innatum_agenda_derivacion_view_form').id,
                'form')],
            'target': 'current',
        }

    def _actividad_para(self, employee, summary, note):
        """Crea una actividad 'Por hacer' para el usuario de un empleado."""
        user = employee.user_id if employee else False
        if not user:
            return
        try:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id, summary=summary, note=note)
        except Exception:  # pragma: no cover - no romper el flujo por la actividad
            _logger.warning('No se pudo crear actividad de derivación %s', self.id)

    def action_confirmar_derivacion(self):
        """El colaborador B confirma la derivación: publica los horarios
        propuestos (estado 'propuesto') y avisa a A (quien derivó) para que
        elija uno y cree el turno."""
        self.ensure_one()
        if self.state != 'derivado':
            raise UserError(_('Solo se confirma una derivación por agendar.'))
        props = self.propuesta_ids  # domain del o2m => solo tipo 'propuesta'
        if not props:
            raise UserError(_('Proponé al menos un horario disponible antes de '
                              'confirmar la derivación.'))
        # Los bloques 'ocupado' eran solo contexto del calendario: se limpian.
        self.env['innatum.agenda.turno.propuesta'].sudo().search(
            [('derivacion_id', '=', self.id), ('tipo', '=', 'ocupado')]).unlink()
        self.state = 'propuesto'
        horarios = Markup('<br/>').join(
            Markup('• %s') % fields.Datetime.to_string(p.date_start)
            for p in props.sorted('date_start'))
        self.message_post(body=Markup(_(
            '<b>%(b)s</b> confirmó la derivación y propuso %(n)s horario(s) '
            'para <b>%(c)s</b>:<br/>%(h)s<br/><i>%(a)s: elegí uno y creá el '
            'turno.</i>')) % {
                'b': self.professional_id.name,
                'n': len(props),
                'c': self.partner_id.name or '-',
                'h': horarios,
                'a': self.derivado_por_id.name or 'Quien derivó'})
        self._actividad_para(
            self.derivado_por_id,
            _('Elegí un horario para tu derivación'),
            _('%(b)s propuso %(n)s horario(s) para %(c)s. Abrí la derivación, '
              'elegí uno y pulsá "Crear turno".') % {
                  'b': self.professional_id.name, 'n': len(props),
                  'c': self.partner_id.name or ''})
        return True

    def action_elegir_horario_calendario(self):
        """Abre el calendario de disponibilidad del profesional para elegir el
        horario de ESTE turno sin ponerlo a ciegas. Muestra en rojo lo ocupado
        (turnos y bloqueos del profesional) y permite hacer clic en un hueco
        libre; al pulsar "Usar este horario" el turno toma esa fecha.

        Reutiliza el planificador de propuestas (innatum.agenda.turno.propuesta)
        que ya se usa en las derivaciones, pero colgando las propuestas de este
        turno normal en lugar de una derivación."""
        self.ensure_one()
        if not self.professional_id:
            raise UserError(_(
                'Elegí primero el profesional para ver su disponibilidad.'))
        if self.state in ('done', 'cancelled'):
            raise UserError(_(
                'Este turno ya está finalizado o cancelado.'))
        self._generar_ocupados_propuesta()
        view = self.env.ref(
            'innatum_agenda_core.innatum_agenda_turno_propuesta_view_calendar')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Disponibilidad de %s · elegí un horario') % (
                self.professional_id.name or ''),
            'res_model': 'innatum.agenda.turno.propuesta',
            'view_mode': 'calendar',
            'views': [(view.id, 'calendar')],
            'domain': [('derivacion_id', '=', self.id)],
            'context': {'default_derivacion_id': self.id,
                        'default_tipo': 'propuesta'},
            'target': 'current',
        }

    def action_planificar_propuestas(self):
        """Abre un calendario con el horario del colaborador que atiende:
        en rojo lo ocupado (sus turnos y bloqueos) y en otro color las
        propuestas. Puede hacer clic en un hueco libre para proponer un
        horario; se guarda como innatum.agenda.turno.propuesta."""
        self.ensure_one()
        if self.state != 'derivado':
            raise UserError(_('Solo se planifican horarios mientras la '
                              'derivación está por agendar.'))
        self._generar_ocupados_propuesta()
        view = self.env.ref(
            'innatum_agenda_core.innatum_agenda_turno_propuesta_view_calendar')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mi horario · proponer para %s') % (
                self.partner_id.name or ''),
            'res_model': 'innatum.agenda.turno.propuesta',
            'view_mode': 'calendar',
            'views': [(view.id, 'calendar')],
            'domain': [('derivacion_id', '=', self.id)],
            'context': {'default_derivacion_id': self.id,
                        'default_tipo': 'propuesta'},
            'target': 'current',
        }

    def _generar_ocupados_propuesta(self):
        """(Re)genera los bloques 'ocupado' de contexto del planificador:
        los turnos tomados y bloqueos del colaborador en las próximas 3
        semanas. Las propuestas ya cargadas se conservan."""
        self.ensure_one()
        Prop = self.env['innatum.agenda.turno.propuesta'].sudo()
        Prop.search([('derivacion_id', '=', self.id),
                     ('tipo', '=', 'ocupado')]).unlink()
        prof = self.professional_id.sudo()
        if not prof:
            return
        desde = fields.Datetime.now()
        hasta = desde + timedelta(days=21)
        vals = []
        Turno = self.env['innatum.agenda.turno'].sudo()
        for t in Turno.search([
                ('id', '!=', self.id),
                ('professional_id', '=', prof.id),
                ('state', 'in', ('reserved', 'confirmed', 'done')),
                ('date_start', '<', hasta), ('date_end', '>', desde)]):
            vals.append({
                'derivacion_id': self.id, 'tipo': 'ocupado',
                'date_start': t.date_start, 'date_end': t.date_end,
                'motivo': _('Turno: %s') % (t.partner_id.name or t.name or ''),
            })
        Bloqueo = self.env['innatum.agenda.bloqueo'].sudo()
        for b in Bloqueo.search([
                ('professional_id', '=', prof.id),
                ('date_start', '<', hasta), ('date_end', '>', desde)]):
            vals.append({
                'derivacion_id': self.id, 'tipo': 'ocupado',
                'date_start': b.date_start, 'date_end': b.date_end,
                'motivo': _('Bloqueo: %s') % (b.motivo or ''),
            })
        if vals:
            Prop.create(vals)


class InnatumAgendaTurnoPropuesta(models.Model):
    """Día/hora que el colaborador que atiende propone para una derivación,
    y también los bloques 'ocupado' que se muestran como contexto en el
    planificador (calendario). Al elegir una propuesta, el turno toma esa
    fecha y pasa al flujo normal (reservado)."""
    _name = 'innatum.agenda.turno.propuesta'
    _description = 'Horario propuesto para una derivación'
    _order = 'date_start'

    derivacion_id = fields.Many2one(
        'innatum.agenda.turno', string='Derivación', required=True,
        ondelete='cascade', index=True,
        domain=[('es_derivacion', '=', True)],
        help='Turno principal de la derivación (estado "derivado") al que '
             'pertenece esta propuesta. Relación explícita y sólida: cada '
             'propuesta cuelga siempre de su derivación de origen.',
    )
    company_id = fields.Many2one(
        related='derivacion_id.company_id', store=True, readonly=True,
    )
    professional_id = fields.Many2one(
        related='derivacion_id.professional_id', store=True, readonly=True,
    )
    parent_state = fields.Selection(
        related='derivacion_id.state', string='Estado del turno',
        readonly=True,
        help='Estado del turno/derivación al que pertenece. Distingue el '
             'planificador de derivación (derivado/propuesto) del selector de '
             'horario de un turno normal (available/reserved/...).',
    )
    tipo = fields.Selection(
        [('propuesta', 'Propuesta'), ('ocupado', 'Ocupado')],
        string='Tipo', default='propuesta', required=True,
        help='"Propuesta": horario que se ofrece al cliente. "Ocupado": '
             'bloque informativo (turno/bloqueo) para ver la disponibilidad '
             'en el planificador.',
    )
    date_start = fields.Datetime(string='Inicio', required=True)
    date_end = fields.Datetime(string='Fin')
    motivo = fields.Char(string='Detalle')
    name = fields.Char(compute='_compute_name')

    @api.depends('tipo', 'motivo', 'date_start')
    def _compute_name(self):
        for rec in self:
            if rec.tipo == 'ocupado':
                rec.name = rec.motivo or _('Ocupado')
            else:
                rec.name = _('Propuesta')

    def _duracion_turno(self):
        """Minutos que dura el turno de la derivación (por el servicio)."""
        self.ensure_one()
        turno = self.derivacion_id
        if turno.duracion_override:
            return int(turno.duracion_override)
        if turno.servicio_id and turno.servicio_id.duracion:
            return int(turno.servicio_id.duracion)
        return 30

    @api.onchange('date_start')
    def _onchange_date_start(self):
        for rec in self:
            if rec.date_start and rec.tipo == 'propuesta':
                rec.date_end = fields.Datetime.add(
                    rec.date_start, minutes=rec._duracion_turno())

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('tipo', 'propuesta')
            # Propuesta sin fin explícito (p.ej. creada en el calendario):
            # el fin lo fija la duración del servicio.
            if vals['tipo'] == 'propuesta' and vals.get('date_start') \
                    and not vals.get('date_end'):
                turno = self.env['innatum.agenda.turno'].browse(
                    vals.get('derivacion_id')).sudo()
                dur = int(turno.duracion_override
                          or (turno.servicio_id.duracion
                              if turno.servicio_id else 0) or 30)
                vals['date_end'] = fields.Datetime.add(
                    fields.Datetime.to_datetime(vals['date_start']),
                    minutes=dur)
        return super().create(vals_list)

    @api.constrains('date_start', 'tipo')
    def _check_futuro(self):
        for rec in self:
            if rec.tipo != 'propuesta':
                continue
            if rec.date_start and rec.date_start < fields.Datetime.now():
                raise ValidationError(_(
                    'No se puede proponer un horario en el pasado.'))

    @api.constrains('date_start', 'date_end', 'tipo')
    def _check_fin_posterior(self):
        for rec in self:
            if rec.tipo != 'propuesta':
                continue
            if rec.date_start and rec.date_end \
                    and rec.date_end <= rec.date_start:
                raise ValidationError(_(
                    'La hora de fin debe ser posterior a la de inicio.'))

    @api.constrains('date_start', 'date_end', 'tipo')
    def _check_libre(self):
        """El horario PROPUESTO no debe cruzarse con turnos ni bloqueos del
        colaborador que atiende (evita proponer un horario ya ocupado). Los
        bloques 'ocupado' son informativos y no se validan."""
        Bloqueo = self.env['innatum.agenda.bloqueo'].sudo()
        Turno = self.env['innatum.agenda.turno'].sudo()
        for rec in self:
            if rec.tipo != 'propuesta':
                continue
            prof = rec.derivacion_id.professional_id
            if not rec.date_start or not rec.date_end or not prof:
                continue
            if Turno.search([
                # Excluir el propio turno: al reprogramar un turno normal, su
                # slot actual no debe contarse como conflicto consigo mismo.
                ('id', '!=', rec.derivacion_id.id),
                ('professional_id', '=', prof.id),
                ('state', 'not in', ('cancelled', 'derivado', 'propuesto')),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ], limit=1):
                raise ValidationError(_(
                    'El horario propuesto (%s) se cruza con otro turno de %s.',
                ) % (fields.Datetime.to_string(rec.date_start), prof.name))
            if Bloqueo.search([
                ('professional_id', '=', prof.id),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ], limit=1):
                raise ValidationError(_(
                    'El horario propuesto (%s) se cruza con un bloqueo de %s.',
                ) % (fields.Datetime.to_string(rec.date_start), prof.name))

    def action_elegir(self):
        """A elige este horario propuesto y crea el turno: toma la fecha,
        registra la trazabilidad completa en el chatter y entra al flujo
        normal (reservado). Se limpian las demás propuestas."""
        self.ensure_one()
        if self.tipo != 'propuesta':
            raise UserError(_('Ese bloque está ocupado; no es una propuesta.'))
        turno = self.derivacion_id
        if turno.state != 'propuesto':
            raise UserError(_(
                'El colaborador aún no confirmó la derivación. Primero debe '
                'proponer horarios y pulsar "Confirmar derivación".'))
        if not turno.servicio_id:
            raise UserError(_(
                'Elegí el servicio de la derivación antes de agendar el '
                'horario (define la duración del turno).'))
        elegido = self.date_start
        # Trazabilidad completa de la derivación en el chatter.
        origen = (Markup(_('<br/>Turno de origen: %s')) % turno.turno_origen_id.name
                  if turno.turno_origen_id else '')
        turno.message_post(body=Markup(_(
            '<b>Turno creado desde derivación</b><br/>'
            'Derivó: <b>%(a)s</b><br/>Atiende: <b>%(b)s</b><br/>'
            'Servicio: %(s)s<br/>Cliente: %(c)s<br/>'
            'Horario elegido: <b>%(h)s</b>%(o)s')) % {
                'a': turno.derivado_por_id.name or '-',
                'b': turno.professional_id.name,
                's': turno.servicio_id.name,
                'c': turno.partner_id.name or '-',
                'h': fields.Datetime.to_string(elegido),
                'o': origen})
        turno.write({
            'date_start': elegido,
            'state': 'reserved',
        })
        # Limpiar TODO el planificador (propuestas + bloques 'ocupado').
        self.sudo().search([('derivacion_id', '=', turno.id)]).unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'innatum.agenda.turno',
            'res_id': turno.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_usar_para_turno(self):
        """Selector de horario de un turno NORMAL (no derivación): toma la
        fecha de este hueco elegido en el calendario y la asigna al turno,
        sin cambiar su estado. La hora de fin se recalcula según la duración
        del servicio. Se limpia el planificador y se vuelve al turno."""
        self.ensure_one()
        if self.tipo != 'propuesta':
            raise UserError(_('Ese bloque está ocupado; elegí un hueco libre.'))
        turno = self.derivacion_id
        if turno.state in ('done', 'cancelled'):
            raise UserError(_(
                'Este turno ya está finalizado o cancelado.'))
        vals = {'date_start': self.date_start}
        # Si el hueco elegido tiene una duración concreta (el colaborador pudo
        # haber estirado/acortado la hora de fin en el calendario), se traslada
        # al turno como duración personalizada. Así un servicio de 30 min puede
        # quedar, por ejemplo, en 45 para este caso particular.
        if self.date_end and self.date_end > self.date_start:
            mins = (self.date_end - self.date_start).total_seconds() / 60.0
            vals['duracion_override'] = mins
        turno.write(vals)
        # Limpiar el planificador de este turno (propuestas + bloques 'ocupado').
        self.sudo().search([('derivacion_id', '=', turno.id)]).unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'innatum.agenda.turno',
            'res_id': turno.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'innatum_agenda_core.innatum_agenda_turno_view_form').id,
                'form')],
            'target': 'current',
        }


class InnatumAgendaTurnoDerivarWizard(models.TransientModel):
    """Wizard para derivar un turno a otro colaborador. Elige el colaborador
    que atenderá y el servicio; al confirmar crea la derivación (turno en
    estado 'derivado')."""
    _name = 'innatum.agenda.turno.derivar.wizard'
    _description = 'Derivar turno a otro colaborador'

    turno_id = fields.Many2one(
        'innatum.agenda.turno', string='Turno de origen', required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='turno_id.company_id', readonly=True,
    )
    origen_id = fields.Many2one(
        related='turno_id.professional_id', string='Deriva', readonly=True,
    )
    partner_id = fields.Many2one(
        related='turno_id.partner_id', string='Cliente', readonly=True,
    )
    receptor_id = fields.Many2one(
        'hr.employee', string='Derivar a (colaborador)', required=True,
        help='Colaborador que atenderá al cliente.',
    )
    servicio_id = fields.Many2one(
        'innatum.agenda.servicio', string='Servicio', required=True,
        help='Servicio que realizará el colaborador. Define la duración.',
    )
    motivo = fields.Text(string='Motivo de la derivación')

    @api.onchange('receptor_id')
    def _onchange_receptor(self):
        """Si el servicio actual no lo ofrece el nuevo receptor, se limpia."""
        if self.receptor_id and self.servicio_id \
                and self.receptor_id not in self.servicio_id.operador_ids:
            self.servicio_id = False

    def action_confirmar(self):
        self.ensure_one()
        turno = self.turno_id
        if self.receptor_id == turno.professional_id:
            raise UserError(_(
                'Elegí a otro colaborador: no podés derivarte el cliente a '
                'vos mismo.'))
        if self.receptor_id not in self.servicio_id.operador_ids:
            raise UserError(_(
                'El colaborador "%(rec)s" no ofrece el servicio "%(serv)s".',
                rec=self.receptor_id.name, serv=self.servicio_id.name))
        deriv = self.env['innatum.agenda.turno'].create({
            'es_derivacion': True,
            'state': 'derivado',
            'professional_id': self.receptor_id.id,
            'servicio_id': self.servicio_id.id,
            'servicio_ids': [(6, 0, self.servicio_id.ids)],
            'partner_id': turno.partner_id.id,
            'derivado_por_id': turno.professional_id.id,
            'turno_origen_id': turno.id,
            'motivo_derivacion': self.motivo,
        })
        turno.message_post(body=_(
            'Cliente derivado a %(rec)s (%(serv)s). Derivación: %(ref)s',
            rec=self.receptor_id.name, serv=self.servicio_id.name,
            ref=deriv.name))
        # Volver a REFRESCAR el mismo turno de origen donde estaba el usuario
        # (no navegar a la derivación). Al recargar, el botón "Derivar" ya no
        # aparece porque el turno tiene una derivación (tiene_derivacion).
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'innatum.agenda.turno',
            'res_id': turno.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'innatum_agenda_core.innatum_agenda_turno_view_form').id,
                'form')],
            'target': 'current',
        }
