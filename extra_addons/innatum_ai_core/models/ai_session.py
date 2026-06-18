# -*- coding: utf-8 -*-
import uuid
from odoo import api, fields, models
from odoo.exceptions import UserError


SESSION_STATES = [
    ('nueva', 'Nueva'),
    # Flujo determinístico de arranque
    ('confirmando_identidad', 'Confirmando identidad (¿eres tú?)'),
    ('esperando_cedula', 'Esperando cédula (usuario nuevo)'),
    ('esperando_nombre', 'Esperando nombre completo'),
    ('menu_principal', 'En menú principal'),
    ('eligiendo_servicio', 'Eligiendo servicio'),
    # Sub-flujo: agendar para un tercero
    ('confirmando_paciente', '¿Reserva para él o para otra persona?'),
    ('esperando_cedula_tercero', 'Esperando cédula del tercero'),
    ('esperando_nombre_tercero', 'Esperando nombre del tercero'),
    # Flujo legacy
    ('identificando_cliente', 'Identificando cliente'),
    ('conversando', 'Conversando'),
    ('buscando_disponibilidad', 'Buscando disponibilidad'),
    ('eligiendo_slot', 'Eligiendo slot'),
    ('confirmando', 'Confirmando datos'),
    ('pendiente_pago', 'Pendiente de pago'),
    ('confirmada', 'Confirmada'),
    ('realizada', 'Realizada'),
    ('cancelada', 'Cancelada'),
    ('con_humano', 'Con humano (handoff)'),
    ('expirada', 'Expirada'),
]

TERMINAL_STATES = ('cancelada', 'realizada', 'expirada')


class AiSession(models.Model):
    """Sesión de conversación WhatsApp con un cliente.

    Una sesión vive desde el primer mensaje hasta que se cierra (cita
    confirmada / cancelada / expirada). El estado guía qué tools puede usar el
    agente IA en cada momento.
    """
    _name = 'innatum.ai.session'
    _description = 'AI Session (WhatsApp)'
    _order = 'create_date desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    token = fields.Char(
        string='Token público',
        default=lambda self: uuid.uuid4().hex,
        required=True,
        copy=False,
    )
    company_id = fields.Many2one('res.company', required=True, index=True)
    wa_from = fields.Char(string='WhatsApp del cliente', required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Cliente identificado')
    turno_id = fields.Many2one(
        'innatum.agenda.turno',
        string='Turno reservado',
        help='Última cita reservada en esta sesión (set por reservar_turno).',
    )
    # Contexto efímero para fast-path: qué servicio/turno está navegando
    # el cliente. Lo seteamos cuando tapea botones interactivos (servicio:CODE,
    # turno:N) para que la siguiente acción tenga el contexto sin depender
    # del LLM.
    current_servicio_code = fields.Char(
        string='Servicio actual (fast-path)',
        help='Código del servicio que el cliente está consultando, seteado '
             'cuando tapea un botón "servicio:CODE".',
    )
    pending_turno_id = fields.Many2one(
        'innatum.agenda.turno',
        string='Turno seleccionado (pendiente)',
        help='Turno que el cliente tapeó pero aún no se reservó (esperando '
             'cédula y nombre). Distinto de turno_id (ya reservado).',
    )
    # Estado del flujo determinístico de identificación
    pending_cedula = fields.Char(
        string='Cédula pendiente',
        help='Cédula que el cliente ingresó pero falta validar o falta completar '
             'con el nombre.',
    )
    pending_cedula_attempts = fields.Integer(
        string='Intentos de cédula inválida',
        default=0,
        help='Contador de intentos fallidos al ingresar cédula. Tras 3 intentos '
             'se deriva a humano.',
    )
    # Sub-flujo: agendar para tercero
    pending_third_party_cedula = fields.Char(
        string='Cédula del tercero (pendiente)',
        help='Cédula de la persona para la que se está reservando, cuando NO '
             'es el cliente que escribe sino un familiar/amigo.',
    )
    state = fields.Selection(SESSION_STATES, default='nueva', required=True, index=True)
    message_ids = fields.One2many('innatum.ai.session.message', 'session_id', string='Mensajes')
    expires_at = fields.Datetime(string='Expira')

    @api.depends('company_id', 'wa_from', 'state')
    def _compute_name(self):
        for s in self:
            s.name = '%s | %s | %s' % (
                s.company_id.name or '?',
                s.wa_from or '?',
                s.state or '?',
            )

    def action_set_state(self, new_state):
        self.ensure_one()
        valid = {code for code, _ in SESSION_STATES}
        if new_state not in valid:
            raise UserError('Estado inválido: %s' % new_state)
        self.state = new_state

    def append_message(self, role, content, tokens_in=0, tokens_out=0, cost_usd=0.0, wamid=None):
        self.ensure_one()
        return self.env['innatum.ai.session.message'].create({
            'session_id': self.id,
            'role': role,
            'content': content,
            'tokens_in': tokens_in,
            'tokens_out': tokens_out,
            'cost_usd': cost_usd,
            'wamid': wamid or False,
        })

    @api.model
    def get_or_create(self, company, wa_from):
        """Devuelve la sesión activa del cliente o crea una nueva si no existe.

        Una sesión es 'activa' si su state NO está en TERMINAL_STATES.
        """
        existing = self.search([
            ('company_id', '=', company.id),
            ('wa_from', '=', wa_from),
            ('state', 'not in', TERMINAL_STATES),
        ], limit=1)
        if existing:
            return existing
        return self.create({
            'company_id': company.id,
            'wa_from': wa_from,
        })


class AiSessionMessage(models.Model):
    """Mensaje dentro de una sesión WhatsApp (rolling chat history).

    NOTA: este modelo es distinto de `innatum.ai.message` (que existe en
    `innatum_ai` para conversaciones internas del ERP). Lo nombramos
    `innatum.ai.session.message` para evitar colisión.
    """
    _name = 'innatum.ai.session.message'
    _description = 'AI Session Message (WhatsApp)'
    _order = 'create_date asc, id asc'

    session_id = fields.Many2one(
        'innatum.ai.session',
        required=True,
        ondelete='cascade',
        index=True,
    )
    role = fields.Selection([
        ('user', 'Cliente'),
        ('assistant', 'Agente'),
        ('system', 'Sistema'),
        ('tool', 'Tool'),
    ], required=True)
    content = fields.Text(required=True)
    wamid = fields.Char(
        string='WhatsApp Message ID',
        index=True,
        help='ID único del mensaje entrante de Meta (wamid). Clave de '
             'idempotencia: si llega un mensaje con un wamid ya registrado, '
             'es una reentrega del webhook y se descarta sin reprocesar.',
    )
    tokens_in = fields.Integer(default=0)
    tokens_out = fields.Integer(default=0)
    cost_usd = fields.Float(default=0.0)
