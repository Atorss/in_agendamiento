# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


PAYMENT_POLICIES = [
    ('sin_cobro', 'Sin cobro previo'),
    ('anticipo', 'Anticipo configurable'),
    ('pago_total', 'Pago total para confirmar'),
]

TONE = [
    ('formal', 'Formal'),
    ('cercano', 'Cercano'),
    ('casual', 'Casual'),
]

ADDRESSING = [
    ('tu', 'Tutear (vos / tú)'),
    ('usted', 'Usted'),
]

EMOJI_USAGE = [
    ('none', 'Sin emojis'),
    ('sutil', 'Sutil (ocasional)'),
    ('expresivo', 'Expresivo'),
]


class BusinessProfile(models.Model):
    """Configuración del negocio (tenant) que define cómo se comporta el agente.

    Cada res.company tiene un único business_profile que deriva de un
    vertical_template y lo personaliza con tono, capacidades activas, política
    de cobro y reglas de reagendamiento.

    Este modelo es la "consola del dueño del negocio": acá el cliente final
    (admin del tenant) configura cómo habla y opera su agente IA. Lo que NO
    está acá son las credenciales técnicas (Meta, Supabase) que viven en
    res.company y solo edita Innatum staff.
    """
    _name = 'innatum.business.profile'
    _description = 'Business Profile'

    # ------------------------------------------------------------------
    # Identidad y vínculos
    # ------------------------------------------------------------------

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        ondelete='cascade',
        default=lambda self: self.env.company,
    )
    vertical_template_id = fields.Many2one(
        'innatum.vertical.template',
        string='Vertical',
        required=True,
        ondelete='restrict',
        help='Define el nicho del negocio (Odontología, Spa, Peluquería, etc.) '
             'y trae los defaults del prompt y reglas.',
    )
    family = fields.Selection(
        related='vertical_template_id.family',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Identidad y branding del agente
    # ------------------------------------------------------------------

    bot_name = fields.Char(
        string='Nombre del agente',
        help='Cómo se presenta el bot ante el cliente. Ej: "Sofía", "Asistente Virtual".',
    )
    business_description_short = fields.Text(
        string='Descripción corta del negocio',
        help='1-2 oraciones que el agente puede usar para presentar el negocio.',
    )

    # ------------------------------------------------------------------
    # Personalidad del agente
    # ------------------------------------------------------------------

    personality_prompt = fields.Text(
        string='Personalidad del agente',
        help='Tono y reglas específicas del negocio. Se concatena al prompt del vertical.',
    )
    tone = fields.Selection(
        TONE, string='Tono', default='cercano',
        help='Cómo de cercano/formal habla el agente.',
    )
    addressing = fields.Selection(
        ADDRESSING, string='Trato', default='tu',
        help='Tuteo (vos/tú) o usted.',
    )
    emoji_usage = fields.Selection(
        EMOJI_USAGE, string='Uso de emojis', default='sutil',
    )
    language_code = fields.Char(
        string='Idioma / locale', default='es-EC',
        help='Locale del agente. Ej: es-EC, es-MX, es-AR.',
    )
    welcome_message = fields.Text(
        string='Mensaje de bienvenida',
        help='Saludo inicial cuando un cliente nuevo escribe por primera vez.',
    )
    error_fallback_message = fields.Text(
        string='Mensaje cuando algo falla',
        default='Lo siento, tuve un problema. Intentemos de nuevo en un momento.',
        help='Qué responde el bot si una herramienta falla o el LLM se cuelga.',
    )

    # ------------------------------------------------------------------
    # Horarios y disponibilidad
    # ------------------------------------------------------------------

    business_hours = fields.Char(
        string='Horario',
        help='Formato libre. Ej: "Lun-Vie 9-18, Sab 9-13". '
             'La zona horaria se toma de la compañía (Configuración → Empresa).',
    )

    # ------------------------------------------------------------------
    # Ubicación y contacto
    #
    # La dirección, teléfono y email se toman de la propia compañía
    # (res.company) — fuente única de verdad ya cargada en el provisioning.
    # Aquí solo añadimos el dato que NO existe en res.company: el enlace de
    # Google Maps, útil para que el agente lo comparta tal cual por WhatsApp.
    # ------------------------------------------------------------------

    google_maps_url = fields.Char(
        string='Enlace de Google Maps',
        help='URL de Google Maps del local. El agente la comparte cuando el '
             'cliente pregunta cómo llegar. La dirección y el teléfono se '
             'toman de la compañía (Configuración → Empresa).',
    )

    # ------------------------------------------------------------------
    # Reglas de agendamiento
    # ------------------------------------------------------------------

    min_advance_booking_hours = fields.Integer(
        string='Anticipación mínima (horas)', default=2,
        help='El cliente no puede agendar dentro de las próximas N horas.',
    )
    max_advance_booking_days = fields.Integer(
        string='Anticipación máxima (días)', default=60,
        help='El cliente no puede agendar a más de N días.',
    )
    allows_rescheduling = fields.Boolean(string='Permite reagendar', default=True)
    min_reschedule_notice_hours = fields.Integer(
        string='Min. horas para reagendar', default=24,
    )
    max_reschedules_per_appointment = fields.Integer(
        string='Max. reagendamientos por cita', default=2,
    )
    allows_cancellation = fields.Boolean(string='Permite cancelar', default=True)
    min_cancellation_notice_hours = fields.Integer(
        string='Min. horas para cancelar', default=24,
    )
    cancellation_policy_text = fields.Text(
        string='Política de cancelación (texto)',
        help='Lo que el agente cita si el cliente pregunta por la política.',
    )

    # ------------------------------------------------------------------
    # Política de cobro
    # ------------------------------------------------------------------

    payment_policy = fields.Selection(
        PAYMENT_POLICIES,
        string='Política de cobro',
        default='sin_cobro',
        required=True,
    )
    anticipo_percent = fields.Float(
        string='% Anticipo', default=0.0,
        help='Solo aplica si payment_policy=anticipo.',
    )

    # ------------------------------------------------------------------
    # Sesión y límites
    # ------------------------------------------------------------------

    agent_enabled = fields.Boolean(
        string='Agente IA activo',
        default=True,
        help='Cuando está apagado, el agente NO responde mensajes de este tenant. '
             'Útil para pausar temporalmente el bot del negocio.',
    )
    max_messages_per_session = fields.Integer(
        string='Max. mensajes por sesión', default=50,
        help='Corta la sesión tras N intercambios para evitar bucles.',
    )
    session_idle_timeout_hours = fields.Integer(
        string='Timeout de sesión inactiva (horas)', default=24,
        help='Cierra sesiones sin actividad después de N horas.',
    )
    send_confirmation_message = fields.Boolean(
        string='Enviar confirmación al agendar', default=True,
        help='Mensaje inmediato confirmando la cita reservada.',
    )

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('company_unique', 'UNIQUE(company_id)',
         'Cada empresa tiene un único Business Profile.'),
    ]

    # ------------------------------------------------------------------
    # Compute / helpers
    # ------------------------------------------------------------------

    @api.depends('company_id', 'vertical_template_id')
    def _compute_name(self):
        for rec in self:
            if rec.company_id and rec.vertical_template_id:
                rec.name = '%s (%s)' % (
                    rec.company_id.name, rec.vertical_template_id.name,
                )
            else:
                rec.name = '(sin nombre)'

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------

    @api.constrains('payment_policy')
    def _check_payment_policy(self):
        valid = dict(PAYMENT_POLICIES)
        for rec in self:
            if rec.payment_policy not in valid:
                raise ValidationError(
                    'Política de cobro inválida: %s' % rec.payment_policy
                )

    @api.constrains('payment_policy', 'anticipo_percent')
    def _check_anticipo_percent(self):
        for rec in self:
            if rec.payment_policy == 'anticipo':
                if rec.anticipo_percent <= 0 or rec.anticipo_percent > 100:
                    raise ValidationError(
                        'Si payment_policy=anticipo, anticipo_percent debe '
                        'estar entre 1 y 100.'
                    )

    @api.constrains('min_advance_booking_hours', 'max_advance_booking_days')
    def _check_booking_window(self):
        for rec in self:
            if rec.min_advance_booking_hours < 0:
                raise ValidationError(
                    'La anticipación mínima no puede ser negativa.'
                )
            if rec.max_advance_booking_days < 1:
                raise ValidationError(
                    'La anticipación máxima debe ser >= 1 día.'
                )

    @api.constrains('max_messages_per_session', 'session_idle_timeout_hours')
    def _check_session_limits(self):
        for rec in self:
            if rec.max_messages_per_session < 5:
                raise ValidationError(
                    'El límite por sesión debe ser >= 5 mensajes.'
                )
            if rec.session_idle_timeout_hours < 1:
                raise ValidationError(
                    'El timeout de sesión debe ser >= 1 hora.'
                )
