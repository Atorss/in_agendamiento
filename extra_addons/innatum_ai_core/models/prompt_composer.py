# -*- coding: utf-8 -*-
"""Servicio que compone el system prompt dinámicamente para una sesión."""
from datetime import datetime
from odoo import api, models


class PromptComposer(models.AbstractModel):
    _name = 'innatum.prompt.composer'
    _description = 'Prompt Composer Service'

    @api.model
    def compose(self, session, capabilities_active=None):
        """Compone el system prompt para una sesión WhatsApp.

        Orden de las secciones:
          1. global_base       — reglas universales del agente
          2. vertical template  — tono del nicho
          3. business personality — tono del tenant
          4. business hours/timezone
          5. capabilities listing — qué tools tiene
          6. rdcm_rules        — defensas anti-alucinación
          7. state_context     — qué puede hacer ahora
        """
        Prompt = self.env['innatum.ai.prompt'].sudo()
        sections = []

        global_base = Prompt.get_active('global_base')
        if global_base:
            sections.append(global_base)

        profile = self.env['innatum.business.profile'].sudo().search([
            ('company_id', '=', session.company_id.id),
            ('active', '=', True),
        ], limit=1)

        # Identidad del bot: nombre + qué negocio representa + qué puede hacer
        # + cómo presentarse. Esto va PRIMERO (tras el global_base) para que el
        # LLM siempre tenga claro su rol antes de leer el resto.
        identity = self._identity_section(session, profile)
        if identity:
            sections.append(identity)

        # Reglas de saludo y memoria conversacional.
        sections.append(self._greeting_rules(session))

        if profile and profile.vertical_template_id:
            vertical_prompt = profile.vertical_template_id.base_personality_prompt
            if vertical_prompt:
                sections.append('## Tono del nicho\n' + vertical_prompt)

        if profile and profile.personality_prompt:
            sections.append('## Personalidad del negocio\n' + profile.personality_prompt)

        ctx_lines = []
        if profile and profile.business_hours:
            ctx_lines.append(f'Horario: {profile.business_hours}')
        if profile and profile.payment_policy:
            ctx_lines.append(f'Política de cobro: {dict(profile._fields["payment_policy"].selection).get(profile.payment_policy)}')
        if profile and profile.allows_rescheduling:
            ctx_lines.append(
                f'Reagendamiento permitido (ventana mínima {profile.min_reschedule_notice_hours}h, '
                f'máx {profile.max_reschedules_per_appointment} reagendas).')
        ctx_lines.append(f'Fecha actual: {datetime.now().isoformat(timespec="minutes")}')
        if ctx_lines:
            sections.append('## Contexto del negocio\n' + '\n'.join(ctx_lines))

        if capabilities_active:
            sections.append(
                '## Capacidades activas\n' +
                '\n'.join('- ' + c for c in capabilities_active))

        rdcm = Prompt.get_active('rdcm_rules')
        if rdcm:
            sections.append('## Defensas anti-alucinación (RDCM)\n' + rdcm)

        state_ctx = self._state_context(session)
        if state_ctx:
            sections.append('## Contexto del estado actual\n' + state_ctx)

        # Contexto efímero del cliente (seteado por fast-path al tapear botones).
        # CRÍTICO para que el LLM use los IDs correctos al reservar.
        ephemeral = self._ephemeral_context(session)
        if ephemeral:
            sections.append('## Estado actual de la sesión (IMPORTANTE)\n' + ephemeral)

        return '\n\n'.join(sections)

    @api.model
    def _identity_section(self, session, profile):
        """Sección de identidad del bot: nombre, negocio, qué hace.

        El LLM lee esto y sabe cómo presentarse en el primer mensaje.
        """
        if not profile:
            return ''
        bot_name = (profile.bot_name or '').strip()
        company_name = (session.company_id.name or '').strip()
        descripcion = (profile.business_description_short or '').strip()
        welcome = (profile.welcome_message or '').strip()

        lines = ['## Identidad del bot']
        if bot_name:
            lines.append(
                f'- Tu nombre es **{bot_name}**. Te presentas con ese nombre.'
            )
        if company_name:
            lines.append(
                f'- Representas a **{company_name}**.'
            )
        if descripcion:
            lines.append(
                f'- Sobre el negocio: {descripcion}'
            )
        # Capacidades de alto nivel del agente
        lines.append(
            '- Puedes ayudar con: agendar citas, consultar horarios/servicios, '
            'reagendar o cancelar citas existentes, y derivar a una persona si '
            'la situación lo requiere.'
        )
        if welcome:
            lines.append(
                f'- Saludo inicial sugerido (úsalo como guía, no copia literal):\n'
                f'  "{welcome}"'
            )
        return '\n'.join(lines) if len(lines) > 1 else ''

    @api.model
    def _greeting_rules(self, session):
        """Reglas para que el LLM no repita saludos en medio de la conversación."""
        # Contar mensajes previos del assistant (excluyendo el actual que aún
        # no se persistió). Si hay 0 = es el primer turno del bot.
        prior_assistant_msgs = self.env['innatum.ai.session.message'].search_count([
            ('session_id', '=', session.id),
            ('role', '=', 'assistant'),
        ])
        prior_user_msgs = self.env['innatum.ai.session.message'].search_count([
            ('session_id', '=', session.id),
            ('role', '=', 'user'),
        ])

        lines = ['## Reglas de saludo y memoria']
        if prior_assistant_msgs == 0:
            lines.append(
                'ESTE ES TU PRIMER MENSAJE en esta conversación. Preséntate '
                'usando tu nombre, menciona el negocio y dile al cliente en qué '
                'puedes ayudarle (1-2 oraciones máximo, con un saludo amable).'
            )
        else:
            lines.append(
                f'YA INICIASTE conversación con este cliente (hay {prior_assistant_msgs} '
                f'mensajes tuyos previos y {prior_user_msgs} del cliente en esta sesión).'
            )
            lines.append(
                '- NO repitas el saludo inicial ni te presentes de nuevo.'
            )
            lines.append(
                '- Si el cliente vuelve a saludar ("hola", "buenas") en medio del '
                'flujo, NO contestes con otro saludo de bienvenida. Reconoce '
                'amablemente y retoma el proceso donde quedaron. Ejemplo: '
                '"¡Hola de nuevo! ¿Quieres continuar con la reserva que '
                'estábamos haciendo?" o "¡Hola! ¿En qué te quedaste? Estábamos '
                'eligiendo el horario para X."'
            )
            lines.append(
                '- Tienes memoria del historial: úsala. Si el cliente ya eligió '
                'servicio o fecha, refleja eso en tu respuesta.'
            )
        return '\n'.join(lines)

    @api.model
    def _ephemeral_context(self, session):
        """Datos dinámicos de la sesión que el LLM necesita ver en CADA prompt.

        Estos campos los setea el fast-path cuando el cliente tapea botones
        interactivos (servicio:CODE, turno:N). El LLM los usa para llamar
        identificar_cliente + reservar_turno con los IDs correctos.
        """
        lines = []
        if session.current_servicio_code:
            lines.append(
                f'- Servicio en curso (code): {session.current_servicio_code}'
            )
        if session.pending_turno_id:
            t = session.pending_turno_id
            lines.append(
                f'- Turno seleccionado pendiente de reservar: turno_id={t.id} '
                f'(referencia "{t.name}"). Al recibir los datos del cliente '
                f'(cédula y nombre), invoca identificar_cliente con esos datos '
                f'y luego reservar_turno con turno_id={t.id}. NO preguntes de '
                f'nuevo el turno; ya está elegido.'
            )
        if session.partner_id:
            lines.append(
                f'- Cliente ya identificado: partner_id={session.partner_id.id}, '
                f'nombre="{session.partner_id.name}". NO le pidas cédula otra vez.'
            )
        return '\n'.join(lines) if lines else ''

    @api.model
    def _state_context(self, session):
        """Texto breve indicando qué puede hacer el agente según el estado."""
        guidance = {
            'nueva': 'El cliente acaba de iniciar conversación. Saluda brevemente y pregunta cómo ayudarlo.',
            # Estados del nuevo flujo determinístico. La lógica primaria la
            # maneja código (fast-path); este texto solo aplica si el LLM
            # llega a tomar control con texto libre.
            'confirmando_identidad': (
                'El cliente recibió el botón "¿Eres [Nombre]?" pero respondió '
                'con texto en vez de tapear el botón. Pregúntale amablemente '
                'que confirme si es esa persona (Sí/No) tocando el botón.'
            ),
            'esperando_cedula': (
                'El cliente debe darnos su cédula ecuatoriana (10 dígitos). '
                'Si te escribió texto que no parece cédula, recuérdale el '
                'formato sin agresividad. NO uses tools en este estado.'
            ),
            'esperando_nombre': (
                'Ya tenemos la cédula del cliente; ahora necesitamos su '
                'nombre completo. Si te escribió algo que no parece un nombre '
                'válido, pídelo de nuevo amablemente. NO uses tools.'
            ),
            'menu_principal': (
                'El cliente ya está identificado y vio el menú principal '
                '(agendar / info / reagendar / cancelar).\n'
                '- REGLA CRÍTICA: NO INVENTES servicios. Si el cliente escribe '
                'un texto que NO corresponde a una intención clara del menú ni '
                'a un nombre exacto de servicio que conoces vía '
                '`consultar_servicios`, NO digas "no veo ese servicio". '
                'En su lugar responde algo natural y abierto como: "No estoy '
                'seguro de qué necesitas. ¿Quieres agendar una nueva cita, '
                'consultar tus citas, reagendar o cancelar?"\n'
                '- Si la intención es clara, ejecuta la tool correspondiente '
                '(`buscar_horarios_disponibles`, `consultar_mis_citas`, '
                '`cancelar_turno`).\n'
                '- Si llega un mensaje muy corto o ambiguo, asume que es '
                'ruido y pregunta amablemente qué necesita.'
            ),
            'identificando_cliente': 'Identifica al cliente con su nombre completo o cédula. Usa `identificar_cliente` cuando lo tengas.',
            'conversando': 'Recopila lo que necesita el cliente. Si menciona agendar, mueve el flujo hacia ofrecer horarios.',
            'buscando_disponibilidad': 'Usa `buscar_horarios_disponibles` con el servicio y rango de fechas que el cliente indicó.',
            'eligiendo_slot': 'El cliente está revisando opciones de horario. Si elige uno claramente, usa `reservar_turno`.',
            'confirmando': 'Resume los datos de la cita y pide confirmación final antes de reservar.',
            'pendiente_pago': 'Cita reservada pero pendiente de pago. NO confirmar definitivamente hasta pago. (Pagos llegan en fase 1C/3).',
            'confirmada': 'Cita confirmada. Responde preguntas sobre la cita si las hay.',
        }
        return guidance.get(session.state, '')
