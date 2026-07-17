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
    # Flujo STAFF (Fase 2: derivaciones por WhatsApp)
    ('staff_menu', 'Staff: menú'),
    ('staff_derivacion', 'Staff: viendo derivación'),
    ('staff_proponiendo', 'Staff: proponiendo horarios'),
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
    pending_slot_token = fields.Char(
        string='Slot seleccionado (modo directo)',
        help='Token opaco "D|prof|iso" del horario que el cliente tapeó en '
             'modo de agenda directa (el turno aún no existe; se crea al '
             'reservar). Equivalente a pending_turno_id pero para Modo B.',
    )
    # Flows-1 — puente a WhatsApp Web. El cliente de WhatsApp Web pierde el
    # submit de la pantalla HORA del Flow (bug de Meta) y reenvía el
    # data_exchange de SERVICIO, ciclando al calendario. Estos flags detectan
    # ese bucle y encaminan al funnel de listas, que sí funciona en Web.
    flow_seen_hora = fields.Boolean(
        string='Flow: pasó por HORA', default=False, copy=False,
        help='Marca transitoria: el Flow sirvió la pantalla HORA. Si luego '
             'llega un data_exchange de SERVICIO, es el bucle de WhatsApp Web.')
    flow_web_incompat = fields.Boolean(
        string='Flow incompatible (WhatsApp Web)', default=False, copy=False,
        help='Detectado el bucle de WhatsApp Web: el próximo "agendar" usa el '
             'funnel de listas en vez del Flow.')
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
    # --- Fase 2: actor de la conversación (staff vs paciente) ---
    actor = fields.Selection([
        ('paciente', 'Paciente'),
        ('staff', 'Staff'),
    ], default='paciente', required=True,
       help='Quién escribe: un paciente o un empleado del tenant '
            '(identificado por su celular en la ficha de empleado).')
    employee_id = fields.Many2one(
        'hr.employee', string='Empleado (si actor=staff)',
        help='Empleado del tenant cuyo celular coincide con wa_from.',
    )
    staff_derivacion_id = fields.Many2one(
        'innatum.agenda.turno', string='Derivación en curso (staff)',
        help='Derivación que el colaborador está atendiendo por WhatsApp.',
    )
    staff_slot_page = fields.Integer(
        string='Página de huecos (staff)', default=0,
    )
    staff_dia = fields.Date(
        string='Día staff en contexto',
        help='Día local (Ecuador) cuyo listado de horas está viendo el '
             'colaborador al proponer horarios de una derivación.')
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

    def ensure_actor(self):
        """Resuelve (y re-verifica) si este número pertenece a un empleado
        ACTIVO del tenant. Cachea employee_id, pero re-verifica en cada
        llamada: un colaborador archivado vuelve a tratarse como paciente.
        Devuelve 'staff' o 'paciente'.
        """
        self.ensure_one()
        emp = self.employee_id
        if emp and emp.active and emp.company_id == self.company_id \
                and emp.wa_number_normalized == self.wa_from:
            if self.actor != 'staff':
                self.actor = 'staff'
            return 'staff'
        emp = self.env['hr.employee'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('wa_number_normalized', '=', self.wa_from),
            ('active', '=', True),
        ], limit=1)
        if emp:
            self.write({'actor': 'staff', 'employee_id': emp.id})
            return 'staff'
        if self.actor != 'paciente' or self.employee_id:
            self.write({'actor': 'paciente', 'employee_id': False})
        return 'paciente'

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

    # ------------------------------------------------------------------
    # Bandeja estilo Chatwoot (client action `innatum_agenda_ai.whatsapp_inbox`)
    # ------------------------------------------------------------------
    # Mapa estado -> color bootstrap para los badges de la bandeja.
    _INBOX_STATE_COLOR = {
        'nueva': 'info',
        'con_humano': 'warning',
        'pendiente_pago': 'warning',
        'confirmada': 'success',
        'realizada': 'success',
        'cancelada': 'secondary',
        'expirada': 'secondary',
    }

    @api.model
    def inbox_conversations(self, domain=None, limit=200):
        """Lista de conversaciones para la columna izquierda de la bandeja.

        Devuelve, por sesión, los datos de cabecera + un preview del último
        mensaje. Las record rules de company scopean automáticamente el
        resultado al tenant del usuario.
        """
        states = dict(SESSION_STATES)
        sessions = self.search(domain or [], limit=limit)
        result = []
        for s in sessions:
            last = s.message_ids[-1] if s.message_ids else False
            result.append({
                'id': s.id,
                'wa_from': s.wa_from or '',
                'partner_name': s.partner_id.display_name or '',
                'company_name': s.company_id.name or '',
                'state': s.state,
                'state_label': states.get(s.state, s.state),
                'state_color': self._INBOX_STATE_COLOR.get(s.state, 'secondary'),
                'turno_name': s.turno_id.display_name or '',
                'last_preview': (last.content or '')[:80] if last else '',
                'last_role': last.role if last else '',
                'last_date': last.create_date if last else s.create_date,
            })
        return result

    @api.model
    def inbox_detail(self, session_id):
        """Hilo de mensajes + ficha de contacto para una conversación."""
        s = self.browse(session_id)
        s.check_access('read')
        states = dict(SESSION_STATES)
        messages = [{
            'id': m.id,
            'role': m.role,
            'content': m.content or '',
            'date': m.create_date,
        } for m in s.message_ids]
        partner = s.partner_id
        return {
            'id': s.id,
            'wa_from': s.wa_from or '',
            'state': s.state,
            'state_label': states.get(s.state, s.state),
            'state_color': self._INBOX_STATE_COLOR.get(s.state, 'secondary'),
            'company_name': s.company_id.name or '',
            'create_date': s.create_date,
            'expires_at': s.expires_at or False,
            'turno_name': s.turno_id.display_name or '',
            'partner': {
                'id': partner.id,
                'name': partner.display_name,
                'phone': partner.phone or partner.mobile or '',
                'email': partner.email or '',
                'vat': partner.vat or '',
            } if partner else False,
            'messages': messages,
        }

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
