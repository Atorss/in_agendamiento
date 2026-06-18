# -*- coding: utf-8 -*-
"""Servicio del agente WhatsApp: orquesta LLM + tools por sesión.

Reutiliza el motor `innatum.ai.engine` (`_call_anthropic/_call_openai/_call_google`)
de innatum_ai pero adapta el loop para trabajar con `innatum.ai.session` (sesión
WhatsApp) en lugar de `innatum.ai.conversation` (sesión interna del ERP).
"""
import json
import logging
import re
from odoo import api, models
from odoo.exceptions import UserError

from .cedula_validator import validate_ec_cedula, extract_cedula

_logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
DEFAULT_HISTORY_WINDOW = 10  # mensajes previos a enviar al LLM

_RE_PERIODO = re.compile(r'^periodo:(AM|PM|NIGHT):([^:]+):(\d{4}-\d{2}-\d{2})$')
_RE_SERVICIO = re.compile(r'^servicio:(.+)$')
_RE_FECHA = re.compile(r'^fecha:(\d{4}-\d{2}-\d{2})$')
_RE_TURNO = re.compile(r'^turno:(\d+)$')
_RE_MENU = re.compile(r'^menu:(.+)$')
_RE_IDENT = re.compile(r'^ident:(yes|no)(?::(\d+))?$')
_RE_CANCEL = re.compile(r'^cancel_turno:(\d+)$')
_RE_CONFIRM_CANCEL = re.compile(r'^confirm_cancel:(\d+)$')
_RE_INFO_TURNO = re.compile(r'^info_turno:(\d+)$')
_RE_BOOK_FOR = re.compile(r'^book_for:(self|other)$')

# Regex genérico para detectar IDs de botón. Si el texto del cliente matchea,
# saltamos los pre-filtros anti-basura (los botones son texto corto válido).
_RE_ANY_BUTTON_ID = re.compile(
    r'^(?:periodo|servicio|fecha|turno|menu|ident|cancel_turno|'
    r'confirm_cancel|info_turno|book_for):'
)
# Detección de "solo emojis / símbolos sin sustancia" para pre-filtro.
# Una palabra "sustantiva" requiere al menos una letra o dígito.
_RE_HAS_ALPHANUM = re.compile(r'[A-Za-z0-9À-ɏ]')
PRE_FILTER_MIN_CHARS = 2
PRE_FILTER_MAX_CHARS = 500


class WhatsappAgent(models.AbstractModel):
    _name = 'innatum.whatsapp.agent'
    _description = 'WhatsApp Agent Service'

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    @api.model
    def process_message(self, session, text, message_type='text', media_id=None):
        """Procesa un mensaje entrante y devuelve la respuesta para enviar.

        Returns:
          dict {'response_text': str, 'session_state': str, 'tool_calls': list?, '_rdcm_warnings': list?}
        """
        if not text and not media_id:
            return {'response_text': '', 'session_state': session.state,
                    'skip_send': True}

        # ====================================================================
        # CAPAS ANTI-ABUSO (cooldown → rate limit → pre-filtros). Ordenadas
        # de más bloqueante a menos. Persistimos el mensaje del cliente igual
        # para auditoría, pero saltamos el procesamiento costoso.
        # ====================================================================
        Throttle = self.env['innatum.wa.throttle'].sudo()
        throttle = Throttle.get_or_create_for(
            session.wa_from, session.company_id,
        )

        # Persistir mensaje entrante (siempre, para audit)
        session.append_message(role='user', content=text or f'[{message_type}:{media_id}]')

        is_button = bool(text and _RE_ANY_BUTTON_ID.match(text.strip()))

        # --- Capa 3: cooldown activo ---
        in_cd, until = throttle.is_in_cooldown()
        if in_cd:
            if throttle.cooldown_notified:
                _logger.info(
                    'wa_throttle: %s in cooldown (silenced), until=%s',
                    session.wa_from, until,
                )
                return {
                    'response_text': '',
                    'session_state': session.state,
                    'skipped_reason': 'cooldown_silenced',
                    'skip_send': True,
                }
            throttle.mark_cooldown_notified()
            try:
                import pytz
                tz = pytz.timezone('America/Guayaquil')
                local = until.replace(tzinfo=pytz.UTC).astimezone(tz)
                until_str = local.strftime('%d/%m %H:%M')
            except Exception:
                until_str = until.strftime('%d/%m %H:%M') if until else ''
            body = (
                f'🔒 Por seguridad, esta conversación está en pausa hasta '
                f'{until_str}. Por favor intenta más tarde.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'fast_path': 'cooldown_notify',
            }

        # --- Capa 2: rate limit por wa_from ---
        allowed, remaining = throttle.check_and_consume_rate()
        if not allowed:
            _logger.info(
                'wa_throttle: %s rate-limited (>30 msg/h)', session.wa_from,
            )
            body = (
                '⏳ Estás enviando demasiados mensajes en poco tiempo. '
                'Por favor espera unos minutos e intenta de nuevo.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'fast_path': 'rate_limited',
            }

        # --- Capa 1: pre-filtros anti-basura (solo para texto NO-botón) ---
        if not is_button:
            prefilter = self._prefilter_text(session, text)
            if prefilter is not None:
                return prefilter

        # FLUJO DETERMINÍSTICO DE ARRANQUE
        # Si la sesión está recién creada (state=nueva), bifurcamos según si
        # ya conocemos el wa_from o no.
        if session.state == 'nueva':
            startup = self._handle_startup(session)
            if startup is not None:
                return startup

        # FAST-PATH PRIMERO: si el cliente tapeó un botón con id conocido,
        # lo manejamos antes de cualquier handler de estado. Importante:
        # debe ir antes de los chequeos de esperando_cedula/nombre porque
        # los botones ident:yes/ident:no se reciben en state=confirmando_identidad.
        fast = self._handle_known_button_id(text, session)
        if fast is not None:
            return fast

        # Si la sesión está esperando cédula o nombre, manejamos esos textos
        # directamente sin involucrar al LLM.
        if session.state == 'esperando_cedula':
            return self._handle_cedula_input(session, text)
        if session.state == 'esperando_nombre':
            return self._handle_nombre_input(session, text)
        if session.state == 'esperando_cedula_tercero':
            return self._handle_cedula_tercero_input(session, text)
        if session.state == 'esperando_nombre_tercero':
            return self._handle_nombre_tercero_input(session, text)
        if session.state == 'confirmando_identidad':
            # El cliente NO tapeó ident:* (porque ya hubiera entrado al fast-path)
            # y en cambio escribió texto. Tratamos como "es otra persona".
            session.partner_id = False
            session.action_set_state('esperando_cedula')
            return self._ask_for_cedula(session, first_time=True)

        # SALUDO en estados post-identificación → re-mostrar menú principal.
        # Si el cliente está en menu_principal/confirmada/pendiente_pago y
        # vuelve a saludar, no le respondemos con LLM genérico ("¡Hola de
        # nuevo!"); le repetimos el menú con sus citas activas.
        if session.state in ('menu_principal', 'confirmada', 'pendiente_pago'):
            if self._is_greeting(text):
                partner = session.partner_id
                if partner:
                    return self._show_main_menu(session, partner)

        # KEYWORDS en menu_principal: si el cliente escribe texto libre que
        # contiene una palabra clave del menú, lo enrutamos al handler
        # determinístico (evita que el LLM invente servicios ante ruido como
        # "Polonio").
        if session.state == 'menu_principal':
            kw = self._match_menu_keyword(text)
            if kw == 'agendar':
                return self._start_agendar_flow(session)
            if kw == 'info':
                return self._show_my_appointments(session, mode='info')
            if kw == 'reagendar':
                return self._show_my_appointments(session, mode='reagendar')
            if kw == 'cancelar':
                return self._show_my_appointments(session, mode='cancelar')

        # En estados post-reserva (confirmada / pendiente_pago) atendemos
        # también keywords del menú: el cliente puede querer info/cancelar/
        # reagendar/agendar otra cita sin volver al menú primero.
        if session.state in ('confirmada', 'pendiente_pago'):
            kw = self._match_menu_keyword(text)
            if kw == 'agendar':
                return self._start_agendar_flow(session)
            if kw == 'info':
                return self._show_my_appointments(session, mode='info')
            if kw == 'reagendar':
                return self._show_my_appointments(session, mode='reagendar')
            if kw == 'cancelar':
                return self._show_my_appointments(session, mode='cancelar')

        # Si la sesión quedó marcada como 'con_humano' por algún motivo
        # histórico (lógica antigua) o como 'expirada' por cualquier flujo,
        # la reseteamos y arrancamos fresh. Esto evita que el cliente quede
        # atrapado sin respuestas.
        if session.state in ('con_humano', 'expirada'):
            old_id = session.id
            if session.state != 'expirada':
                session.action_set_state('expirada')
            Session = self.env['innatum.ai.session'].sudo()
            new_session = Session.get_or_create(
                session.company_id, session.wa_from,
            )
            _logger.info(
                'Stale session %s reset → new session %s',
                old_id, new_session.id,
            )
            startup = self._handle_startup(new_session)
            if startup is None:
                return {
                    'response_text': '',
                    'session_state': new_session.state,
                    'session_id_override': new_session.id,
                    'previous_session_id': old_id,
                    'skip_send': True,
                }
            startup['session_id_override'] = new_session.id
            startup['previous_session_id'] = old_id
            return startup

        provider = self._get_active_provider()
        if not provider:
            return {
                'response_text': 'El agente no está disponible en este momento.',
                'session_state': session.state,
                'error': 'no_active_provider',
            }

        Engine = self.env['innatum.ai.engine']
        Composer = self.env['innatum.prompt.composer']
        Rdcm = self.env['innatum.rdcm']

        Engine = Engine.with_context(
            ai_source='whatsapp_agent',
            ai_record_ref=f'innatum.ai.session,{session.id}',
        )

        tool_schemas, available_tools = self._get_agent_tools(session)
        system_prompt = Composer.compose(
            session=session,
            capabilities_active=[t.name for t in available_tools.values()],
        )
        messages = self._build_messages_history(session)

        caller = Engine._get_api_caller(provider)

        final_text = ''
        iterations = 0
        all_tool_calls_summary = []
        final_tokens_in = 0
        final_tokens_out = 0

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1
            Engine._check_cost_limits(provider)

            response = caller(
                provider,
                messages,
                tools=tool_schemas if tool_schemas else None,
                system=system_prompt,
            )

            content_blocks = response.get('content', []) or []
            stop_reason = response.get('stop_reason', 'end_turn')
            usage = Engine._extract_usage(response, provider.provider_type)
            tokens_in = usage.get('input_tokens', 0)
            tokens_out = usage.get('output_tokens', 0)

            text_parts = []
            tool_use_blocks = []
            for block in content_blocks:
                btype = block.get('type')
                if btype == 'text':
                    text_parts.append(block.get('text', ''))
                elif btype == 'tool_use':
                    tool_use_blocks.append(block)

            current_text = '\n'.join(t for t in text_parts if t).strip()

            if not tool_use_blocks or stop_reason != 'tool_use':
                final_text = current_text
                # NO guardamos aquí. Se guarda después de armar meta_payload,
                # para poder persistir el BODY del interactive (corto) en lugar
                # del response_text del LLM (que tiende a listar y contamina
                # el historial del LLM en próximos turnos).
                final_tokens_in = tokens_in
                final_tokens_out = tokens_out
                break

            # Persistir el assistant message SOLO si tiene texto real.
            # NO guardamos "(ejecutando herramientas...)" porque ese placeholder,
            # al volver al historial en la próxima request, el LLM aprende a
            # copiarlo como si fuera respuesta válida → bug.
            if current_text:
                session.append_message(
                    role='assistant', content=current_text,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                )

            # Construir el siguiente turno: assistant con content_blocks (Anthropic style)
            messages.append({'role': 'assistant', 'content': content_blocks})

            tool_results_for_api = []
            for tb in tool_use_blocks:
                tool_name = tb.get('name')
                tool_input = tb.get('input') or {}
                tool_id = tb.get('id')

                tool = available_tools.get(tool_name)
                if not tool:
                    result = {'error': f'Herramienta no encontrada: {tool_name}'}
                else:
                    _logger.info(
                        'Tool %s called for session %s: %s',
                        tool_name, session.id,
                        json.dumps(tool_input, ensure_ascii=False)[:200],
                    )
                    try:
                        result = tool.execute_tool(
                            tool_input,
                            user=self.env.user,
                            session=session,
                        )
                    except UserError as ue:
                        result = {'error': str(ue)}
                    except Exception as exc:
                        _logger.exception('Tool %s crashed', tool_name)
                        result = {'error': str(exc)}

                all_tool_calls_summary.append({'tool': tool_name, 'input': tool_input, 'result': result})

                tool_results_for_api.append({
                    'type': 'tool_result',
                    'tool_use_id': tool_id,
                    'content': json.dumps(result, ensure_ascii=False, default=str),
                })

            # Persistir resultados como mensaje "tool"
            session.append_message(
                role='tool',
                content=json.dumps(all_tool_calls_summary[-len(tool_use_blocks):], ensure_ascii=False, default=str),
            )

            messages.append({'role': 'user', 'content': tool_results_for_api})

        if iterations >= MAX_TOOL_ITERATIONS:
            final_text = (final_text or '') + '\n\n⚠️ Se alcanzó el límite de iteraciones de herramientas.'

        # Post-process (RDCM Layer 3) — solo aplica si el agente devolvió JSON con extracted.
        # En Fase 1B asumimos texto natural; el campo extracted es opcional.
        try:
            parsed = self._maybe_parse_structured(final_text)
        except Exception:
            parsed = None

        rdcm_warnings = []
        if parsed:
            processed = Rdcm.post_process(parsed, session)
            rdcm_warnings = processed.get('_rdcm_warnings') or []
            # Si el agente devolvió JSON con 'message', usar ese; si no, mantener final_text
            if isinstance(processed.get('message'), str):
                final_text = processed['message']

        # Construir meta_payload interactive si conviene (botones / lista).
        # Pasamos el response_text del LLM (por si algún caso lo usa como
        # fallback), pero los bodies son hardcoded cortos.
        meta_payload = None
        try:
            meta_payload = self._build_meta_interactive(
                all_tool_calls_summary, session.wa_from,
                response_text=final_text,
            )
        except Exception:
            _logger.exception('Fallo construyendo meta_payload')
            meta_payload = None

        # CRÍTICO: persistir el assistant message en sesión.
        # Si hay meta_payload, guardamos SOLO el body del interactive (corto,
        # útil para contexto) en lugar del response_text largo del LLM. Si
        # guardáramos el response_text largo, el LLM en próximos turnos lo
        # vería en su historial y aprendería a listar contenido en texto
        # plano (lo que romperla la UX interactive).
        if meta_payload:
            body_text = (meta_payload.get('interactive', {})
                                     .get('body', {}).get('text', ''))
            session_content = body_text or final_text or '(interactive)'
        else:
            session_content = final_text or '(sin texto)'

        session.append_message(
            role='assistant',
            content=session_content,
            tokens_in=final_tokens_in,
            tokens_out=final_tokens_out,
        )

        return {
            'response_text': final_text,
            'session_state': session.state,
            'tool_calls': all_tool_calls_summary,
            'meta_payload': meta_payload,
            '_rdcm_warnings': rdcm_warnings,
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_active_provider(self):
        """Devuelve el provider activo con menor `sequence`."""
        return self.env['innatum.ai.provider'].sudo().search(
            [('active', '=', True)], order='sequence asc', limit=1)

    def _get_agent_tools(self, session):
        """Filtra tools tipo wa_agent activas y accesibles para el usuario actual.

        En Fase 1B todos los tenants ven todas las tools wa_agent activas. En Fase 2
        filtramos por capacidades activas del business_profile.
        """
        tools = self.env['innatum.ai.tool'].sudo().search([
            ('active', '=', True),
            ('tool_type', '=', 'wa_agent'),
        ])
        schemas = []
        available = {}
        for tool in tools:
            schemas.append(tool._get_tool_schema())
            available[tool.name] = tool
        return schemas, available

    def _build_messages_history(self, session, window=DEFAULT_HISTORY_WINDOW):
        """Construye lista de mensajes en formato API (Anthropic-like) para el LLM.

        Toma los últimos `window` mensajes user/assistant; ignora system y tool
        (esos viven en system_prompt y en tool_result respectivamente).
        """
        msgs = session.message_ids.sorted('id')[-window:]
        history = []
        for m in msgs:
            if m.role in ('user', 'assistant') and m.content:
                history.append({'role': m.role, 'content': m.content})
        return history

    # -------------------------------------------------------------------------
    # Fast-path: manejo determinístico de IDs de botones interactivos
    # -------------------------------------------------------------------------

    def _handle_known_button_id(self, text, session):
        """Si `text` es un id de botón conocido, ejecuta la tool y devuelve
        el response listo, saltando el LLM.

        Maneja:
          - servicio:CODE → consultar_regimen_servicio(CODE) + setea session
          - fecha:YYYY-MM-DD → buscar_horarios_disponibles(servicio_code de sesión, fecha)
          - periodo:AM|PM|NIGHT:CODE:FECHA → buscar_horarios_disponibles con período
          - turno:N → setea pending_turno_id + pide cédula/nombre (texto plano)
          - menu:otra_fecha → pide fecha en texto plano

        Devuelve None si no matchea ningún patrón conocido (sigue flujo normal).
        """
        if not text:
            return None
        text = text.strip()
        Primitives = self.env['innatum.agenda.scheduling.primitives']

        # === servicio:CODE → mostrar régimen + fechas próximas ===
        m = _RE_SERVICIO.match(text)
        if m:
            code = m.group(1)
            _logger.info('Fast-path servicio: session=%s code=%s', session.id, code)
            session.current_servicio_code = code
            result = Primitives.summarize_schedule(
                servicio_code=code, company=session.company_id,
            )
            tool_summary = {
                'tool': 'consultar_regimen_servicio',
                'input': {'servicio_code': code},
                'result': result,
            }
            return self._fast_path_response(session, tool_summary, 'servicio')

        # === fecha:YYYY-MM-DD → buscar horarios de ese día ===
        m = _RE_FECHA.match(text)
        if m:
            fecha = m.group(1)
            code = session.current_servicio_code
            if not code:
                # No tenemos contexto del servicio: caer al LLM para que
                # pregunte al cliente qué servicio quiere.
                return None
            _logger.info(
                'Fast-path fecha: session=%s code=%s fecha=%s',
                session.id, code, fecha,
            )
            result = Primitives.find_availability(
                servicio_code=code, fecha=fecha, company=session.company_id,
            )
            tool_summary = {
                'tool': 'buscar_horarios_disponibles',
                'input': {'servicio_code': code, 'fecha': fecha},
                'result': result,
            }
            return self._fast_path_response(session, tool_summary, 'fecha')

        # === periodo:AM|PM|NIGHT:CODE:FECHA → filtrar slots por período ===
        m = _RE_PERIODO.match(text)
        if m:
            periodo, code, fecha = m.group(1), m.group(2), m.group(3)
            _logger.info(
                'Fast-path periodo: session=%s code=%s fecha=%s periodo=%s',
                session.id, code, fecha, periodo,
            )
            session.current_servicio_code = code
            result = Primitives.find_availability(
                servicio_code=code, fecha=fecha, periodo=periodo,
                company=session.company_id,
            )
            tool_summary = {
                'tool': 'buscar_horarios_disponibles',
                'input': {'servicio_code': code, 'fecha': fecha, 'periodo': periodo},
                'result': result,
            }
            return self._fast_path_response(session, tool_summary, 'periodo')

        # === turno:N → preguntar si la cita es para él o para otra persona ===
        # NO reservar todavía. Mostrar 2 botones:
        #   ✅ Es para mí       → book_for:self  (reserva con session.partner_id)
        #   👤 Es para otra persona → book_for:other (entra a sub-flujo cédula+nombre)
        m = _RE_TURNO.match(text)
        if m:
            turno_id = int(m.group(1))
            turno = self.env['innatum.agenda.turno'].sudo().browse(turno_id)
            if not turno.exists():
                return None
            _logger.info(
                'Fast-path turno: session=%s turno_id=%s partner_id=%s',
                session.id, turno_id, session.partner_id.id or None,
            )
            session.pending_turno_id = turno_id
            return self._ask_who_is_patient(session, turno)

        # === book_for:self|other → bifurcación paciente ===
        m = _RE_BOOK_FOR.match(text)
        if m:
            choice = m.group(1)
            if choice == 'self':
                if not session.pending_turno_id:
                    return self._text_response(
                        session,
                        '⚠️ No tengo un turno pendiente. Por favor selecciona '
                        'un horario primero.',
                    )
                if not session.partner_id:
                    # Defensivo: caso edge sin partner. Pedir cédula propia.
                    session.action_set_state('esperando_cedula')
                    return self._ask_for_cedula(session, first_time=True)
                return self._do_reserve_with_partner(
                    session, session.partner_id.id,
                )
            # choice == 'other' → entrar al sub-flujo de cédula del tercero
            session.action_set_state('esperando_cedula_tercero')
            body = (
                '👤 Indícame la cédula de la persona para la que reservas '
                '(10 dígitos).'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                '_rdcm_warnings': [],
                'fast_path': 'ask_cedula_tercero',
            }

        # === ident:yes:N o ident:no → confirmar identidad ===
        m = _RE_IDENT.match(text)
        if m:
            choice = m.group(1)
            if choice == 'yes':
                partner_id = int(m.group(2)) if m.group(2) else None
                partner = self.env['res.partner'].sudo().browse(partner_id) if partner_id else None
                if partner and partner.exists():
                    session.partner_id = partner.id
                    return self._show_main_menu(session, partner)
            # choice == 'no' → tratar como usuario nuevo
            session.partner_id = False
            session.action_set_state('esperando_cedula')
            return self._ask_for_cedula(session, first_time=True)

        # === menu:agendar → comenzar flujo de agendamiento ===
        m = _RE_MENU.match(text)
        if m:
            kind = m.group(1)
            if kind == 'agendar':
                return self._start_agendar_flow(session)
            if kind == 'info':
                return self._show_my_appointments(session, mode='info')
            if kind == 'reagendar':
                return self._show_my_appointments(session, mode='reagendar')
            if kind == 'cancelar':
                return self._show_my_appointments(session, mode='cancelar')
            if kind == 'otra_fecha':
                _logger.info('Fast-path menu:otra_fecha session=%s', session.id)
                ask = (
                    '📅 Indícame la fecha en la que deseas reservar '
                    '(por ejemplo "el 27 de mayo" o "2026-05-27").'
                )
                session.append_message(role='assistant', content=ask)
                return {
                    'response_text': ask,
                    'session_state': session.state,
                    'tool_calls': [],
                    'meta_payload': None,
                    '_rdcm_warnings': [],
                    'fast_path': 'menu:otra_fecha',
                }

        # === info_turno:N → mostrar info detallada de un turno ===
        m = _RE_INFO_TURNO.match(text)
        if m:
            turno_id = int(m.group(1))
            return self._show_turno_info(session, turno_id)

        # === cancel_turno:N → pedir confirmación antes de cancelar ===
        m = _RE_CANCEL.match(text)
        if m:
            turno_id = int(m.group(1))
            return self._ask_cancel_confirmation(session, turno_id)

        # === confirm_cancel:N → ejecutar cancelación ===
        m = _RE_CONFIRM_CANCEL.match(text)
        if m:
            turno_id = int(m.group(1))
            return self._execute_cancel(session, turno_id)

        return None

    # -------------------------------------------------------------------------
    # Flujo determinístico de identificación + menú principal
    # -------------------------------------------------------------------------

    def _handle_startup(self, session):
        """Primer mensaje de la sesión (state=nueva).

        - Busca partner por wa_from (mobile OR phone) en este tenant.
        - Si encuentra → state=confirmando_identidad + pregunta "¿eres tú?".
        - Si no encuentra → state=esperando_cedula + pide cédula.
        """
        wa_from = (session.wa_from or '').strip()
        if not wa_from:
            return None

        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([
            '|', ('mobile', '=', wa_from), ('phone', '=', wa_from),
            ('company_id', 'in', [False, session.company_id.id]),
        ], limit=1)

        if partner:
            # Cliente conocido → confirmar identidad
            session.action_set_state('confirmando_identidad')
            body = (
                f'¡Hola! 👋 ¿Eres {partner.name}? Confírmame para continuar.'
            )
            payload = self._payload_buttons(
                session.wa_from,
                header='👤 Identificación',
                body=body,
                buttons=[
                    {'id': f'ident:yes:{partner.id}',
                     'title': f'✅ Sí, soy {partner.name.split()[0][:14]}'},
                    {'id': 'ident:no',
                     'title': '❌ No, soy otra persona'},
                ],
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': payload,
                '_rdcm_warnings': [],
                'fast_path': 'startup_existing',
            }

        # Cliente nuevo → pedir cédula
        session.action_set_state('esperando_cedula')
        # Identidad: priorizar bot_name del profile; fallback al nombre del tenant
        profile = self.env['innatum.business.profile'].sudo().search([
            ('company_id', '=', session.company_id.id),
            ('active', '=', True),
        ], limit=1)
        bot_label = (profile.bot_name or '').strip() if profile else ''
        if not bot_label:
            bot_label = session.company_id.name or 'el asistente'
        # Saludo + pregunta inicial en el mismo mensaje
        body = (
            f'¡Hola! 👋 Soy {bot_label}, el asistente virtual. Para empezar, '
            f'¿me indicas tu número de cédula? (10 dígitos)'
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'startup_new',
        }

    def _handle_cedula_input(self, session, text):
        """Procesa la cédula que el cliente acaba de escribir.

        - Extrae 10 dígitos del texto.
        - Valida con algoritmo módulo 10.
        - Si OK: guardar y pasar a esperando_nombre.
        - Si KO: incrementar contador. 3 intentos → expirar la sesión con
          mensaje cordial para que el cliente reinicie escribiendo "Hola".
        """
        cedula = extract_cedula(text)
        valid, err = validate_ec_cedula(cedula) if cedula else (False, 'No pude reconocer una cédula en tu mensaje.')

        if not valid:
            session.pending_cedula_attempts = (session.pending_cedula_attempts or 0) + 1
            attempts_left = max(0, 3 - session.pending_cedula_attempts)
            if session.pending_cedula_attempts >= 3:
                # Cerrar la sesión (sin handoff) y aplicar cooldown
                # progresivo: 1ra vez 2h, 2da en 24h escala a 24h.
                session.action_set_state('expirada')
                Throttle = self.env['innatum.wa.throttle'].sudo()
                throttle = Throttle.get_or_create_for(
                    session.wa_from, session.company_id,
                )
                until = throttle.record_expiration()
                # Convertir a hora local para el aviso
                try:
                    import pytz
                    tz = pytz.timezone('America/Guayaquil')
                    until_str = until.replace(tzinfo=pytz.UTC).astimezone(tz).strftime('%d/%m %H:%M')
                except Exception:
                    until_str = until.strftime('%d/%m %H:%M') if until else ''
                # Marcar notificado para que el bloqueo de capa 3 (en el
                # próximo mensaje) silencie en vez de re-avisar.
                throttle.mark_cooldown_notified()
                body = (
                    f'❌ No pude validar tu cédula tras varios intentos. '
                    f'Por seguridad pausaremos esta conversación hasta '
                    f'{until_str}. Verifica tu número e inténtalo más '
                    f'tarde escribiéndome *Hola*.'
                )
                session.append_message(role='assistant', content=body)
                return {
                    'response_text': body,
                    'session_state': session.state,
                    'tool_calls': [],
                    'meta_payload': None,
                    '_rdcm_warnings': [],
                    'fast_path': 'cedula_max_attempts',
                }
            body = (
                f'❌ {err} '
                f'Te quedan {attempts_left} intento(s). '
                f'Ingresa una cédula ecuatoriana válida de 10 dígitos.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                '_rdcm_warnings': [],
                'fast_path': 'cedula_invalid',
            }

        # Cédula válida → buscar primero si ya existe partner con esa cédula
        Partner = self.env['res.partner'].sudo()
        existing = Partner.search([
            ('vat', '=', cedula),
            ('company_id', 'in', [False, session.company_id.id]),
        ], limit=1)
        if existing:
            # Ya existe → vincular y mostrar menú
            session.partner_id = existing.id
            session.pending_cedula = False
            session.pending_cedula_attempts = 0
            return self._show_main_menu(session, existing)

        # No existe → guardar cédula + pedir nombre
        session.pending_cedula = cedula
        session.pending_cedula_attempts = 0
        session.action_set_state('esperando_nombre')
        body = (
            f'✅ Cédula registrada. Ahora, ¿cuál es tu nombre completo?'
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'cedula_ok',
        }

    def _handle_nombre_input(self, session, text):
        """Cliente acaba de escribir su nombre. Crea el partner y muestra menú."""
        name = (text or '').strip()
        if len(name) < 3:
            body = '🔁 Por favor escribe tu nombre completo (mínimo 3 caracteres).'
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                '_rdcm_warnings': [],
                'fast_path': 'nombre_invalid',
            }

        Partner = self.env['res.partner'].sudo()
        partner = Partner.create({
            'name': name,
            'vat': session.pending_cedula or False,
            'mobile': session.wa_from or False,
            'company_id': session.company_id.id,
            'comment': 'Origen: agente WhatsApp',
        })
        session.partner_id = partner.id
        session.pending_cedula = False
        # Cliente NUEVO → menú simple (no tiene citas activas)
        return self._show_main_menu(session, partner)

    def _prefilter_text(self, session, text):
        """Capa 1: filtros baratos antes de pegar al LLM.

        Devuelve un dict de respuesta (texto plantilla) si el mensaje NO
        debe pasar al flujo normal, o None si pasa.

        Filtros aplicados:
          - Texto vacío o solo whitespace
          - Mensaje sin caracteres alfanuméricos (solo emojis/símbolos)
          - Muy corto (< PRE_FILTER_MIN_CHARS)
          - Muy largo (> PRE_FILTER_MAX_CHARS)
          - Idéntico al último mensaje del cliente (eco) → silencio
        """
        if text is None:
            return None
        clean = text.strip()
        # 1) Vacío o solo whitespace
        if not clean:
            body = (
                '🤔 No entendí tu mensaje. Si quieres agendar una cita, '
                'escríbeme *Hola* o *Agendar*.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'fast_path': 'prefilter_empty',
            }
        # 2) Solo emojis/símbolos (sin alfanumérico)
        if not _RE_HAS_ALPHANUM.search(clean):
            body = (
                '🤔 No entendí tu mensaje. Si quieres agendar una cita, '
                'escríbeme *Hola* o *Agendar*.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'fast_path': 'prefilter_no_alphanum',
            }
        # 3) Muy corto (excepto botones que ya pasaron por _RE_ANY_BUTTON_ID)
        if len(clean) < PRE_FILTER_MIN_CHARS:
            body = (
                'Por favor escríbeme algo más claro 🙂. Si quieres agendar '
                'una cita escribe *Hola*.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'fast_path': 'prefilter_too_short',
            }
        # 4) Muy largo
        if len(clean) > PRE_FILTER_MAX_CHARS:
            body = (
                '📝 Tu mensaje es muy extenso. Por favor escríbeme algo '
                'breve para poder ayudarte.'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'fast_path': 'prefilter_too_long',
            }
        # 5) Eco: ¿el cliente envió el MISMO mensaje que el anterior?
        # Buscamos el penúltimo mensaje del cliente (porque acabamos de
        # persistir el actual). Si es idéntico, silencio.
        Msg = self.env['innatum.ai.session.message']
        prev_user = Msg.search([
            ('session_id', '=', session.id),
            ('role', '=', 'user'),
        ], order='create_date desc, id desc', limit=2)
        if len(prev_user) == 2 and prev_user[1].content == clean:
            _logger.info(
                'prefilter: echo from session=%s wa_from=%s',
                session.id, session.wa_from,
            )
            return {
                'response_text': '',
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                'skip_send': True,
                'fast_path': 'prefilter_echo',
            }
        return None

    def _is_greeting(self, text):
        """Detecta si el texto es un saludo corto.

        Solo aplica a textos breves (≤30 chars) que arrancan con un patrón
        de saludo. Evita falsos positivos con frases largas que mencionan
        'hola' incidentalmente.
        """
        if not text:
            return False
        t = text.strip().lower()
        if not t or len(t) > 30:
            return False
        greetings = (
            'hola', 'holaa', 'holi', 'buenas', 'buen dia', 'buen día',
            'buenos dias', 'buenos días', 'buenas tardes', 'buenas noches',
            'hi', 'hello', 'ola', 'saludos', 'qué tal', 'que tal',
        )
        return any(t == g or t.startswith(g + ' ') or t.startswith(g + ',') or
                   t.startswith(g + '!') or t.startswith(g + '.')
                   for g in greetings)

    def _match_menu_keyword(self, text):
        """Detecta palabras clave de intención en texto libre.

        Devuelve 'agendar', 'info', 'reagendar', 'cancelar' o None.
        Solo aplica cuando estamos en menu_principal y queremos evitar que
        el LLM invente servicios ante ruido.
        """
        if not text:
            return None
        t = text.strip().lower()
        if len(t) > 80:
            # Texto largo → mejor LLM, no keyword.
            return None
        # Orden importa: reagendar antes que agendar (substring).
        if any(k in t for k in ('reagendar', 'cambiar fecha', 'mover cita',
                                 'mover mi cita')):
            return 'reagendar'
        if any(k in t for k in ('cancelar', 'anular', 'quitar cita',
                                 'borrar cita')):
            return 'cancelar'
        if any(k in t for k in ('agendar', 'reservar', 'nueva cita',
                                 'pedir cita', 'sacar cita', 'sacar turno',
                                 'nuevo turno')):
            return 'agendar'
        if any(k in t for k in ('info', 'mis citas', 'mi cita',
                                 'mis turnos', 'mi turno', 'consultar')):
            return 'info'
        return None

    def _ask_who_is_patient(self, session, turno):
        """Pregunta si la reserva es para el cliente o para otra persona.

        Llamado tras tap `turno:N`. Muestra 2 botones: book_for:self,
        book_for:other. Guarda pending_turno_id para retomar tras la decisión.
        """
        session.action_set_state('confirmando_paciente')
        try:
            servicio_nombre = (turno.servicio_id.name or '').strip()
        except Exception:
            servicio_nombre = ''
        # Convertir hora UTC del turno a hora local del tenant para que
        # el cliente vea el mismo formato que verá en el resumen final.
        fecha_str = ''
        try:
            if turno.date_start:
                import pytz
                tz = pytz.timezone('America/Guayaquil')
                dt_local = pytz.UTC.localize(turno.date_start).astimezone(tz)
                fecha_str = dt_local.strftime('%d/%m %H:%M')
        except Exception:
            fecha_str = ''
        partes = [p for p in [servicio_nombre, fecha_str] if p]
        contexto = (' — ' + ' · '.join(partes)) if partes else ''
        body = (
            f'¿Esta cita es para ti o para otra persona?{contexto}'
        )
        payload = self._payload_buttons(
            session.wa_from,
            header='👤 ¿Quién es el paciente?',
            body=body,
            buttons=[
                {'id': 'book_for:self', 'title': '✅ Es para mí'},
                {'id': 'book_for:other', 'title': '👤 Para otra persona'},
            ],
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': payload,
            '_rdcm_warnings': [],
            'fast_path': 'ask_who_is_patient',
        }

    def _do_reserve_with_partner(self, session, partner_id):
        """Ejecuta la reserva con un partner_id dado, arma el resumen y
        responde como TEXTO PLANO (sin botones, según decisión del cliente).

        Usado por book_for:self y al final del sub-flujo de tercero.
        """
        if not session.pending_turno_id:
            return self._text_response(
                session,
                '⚠️ No tengo un turno pendiente para reservar. '
                'Por favor elige un horario.',
            )
        turno_id = session.pending_turno_id.id
        result = self.env['flow.scheduling.tools'].sudo().reservar_turno(
            {
                'turno_id': turno_id,
                'partner_id': partner_id,
                'servicio_code': session.current_servicio_code or None,
            },
            session=session,
        )
        if not result.get('exito'):
            err = result.get('error', 'No fue posible reservar.')
            return self._text_response(session, f'⚠️ {err}')
        # Limpiar cualquier dato pendiente del sub-flujo de tercero
        session.pending_third_party_cedula = False
        lines = ['✅ Cita reservada', '']
        if result.get('paciente'):
            lines.append(f"👤 Paciente: {result['paciente']}")
        if result.get('especialidad'):
            lines.append(f"🏷️ Servicio: {result['especialidad']}")
        if result.get('professional'):
            lines.append(f"🩺 Profesional: {result['professional']}")
        fecha_hora = ' '.join(
            p for p in [result.get('fecha', ''), result.get('hora', '')] if p
        ).strip()
        if fecha_hora:
            lines.append(f"📅 Fecha: {fecha_hora}")
        if result.get('referencia'):
            lines.append(f"🔖 Ref: {result['referencia']}")
        if result.get('estado'):
            lines.append(f"📌 Estado: {result['estado']}")
        body = '\n'.join(lines)
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [{
                'tool': 'reservar_turno',
                'input': {'turno_id': turno_id, 'partner_id': partner_id},
                'result': result,
            }],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'reservation_done',
        }

    def _handle_cedula_tercero_input(self, session, text):
        """Valida la cédula del tercero. Si OK: pasa a esperando_nombre_tercero.

        Tolera 3 intentos como el flujo de usuario nuevo, pero al fallar NO
        deriva a humano sino que vuelve a confirmando_paciente para que el
        cliente decida si insiste o reserva para él.
        """
        cedula = extract_cedula(text)
        valid, err = (
            validate_ec_cedula(cedula) if cedula
            else (False, 'No pude reconocer una cédula en tu mensaje.')
        )
        if not valid:
            body = (
                f'❌ {err} Por favor escribe la cédula del paciente '
                f'(10 dígitos ecuatorianos válidos).'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                '_rdcm_warnings': [],
                'fast_path': 'cedula_tercero_invalid',
            }
        # Cédula válida → buscar si ya existe el partner
        Partner = self.env['res.partner'].sudo()
        existing = Partner.search([
            ('vat', '=', cedula),
            ('company_id', 'in', [False, session.company_id.id]),
        ], limit=1)
        if existing:
            # Ya existe → reservar directamente con ese partner, sin pedir nombre
            session.pending_third_party_cedula = False
            return self._do_reserve_with_partner(session, existing.id)
        # No existe → guardamos cédula y pedimos nombre
        session.pending_third_party_cedula = cedula
        session.action_set_state('esperando_nombre_tercero')
        body = (
            '✅ Cédula registrada. Ahora indícame el nombre completo del '
            'paciente.'
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'ask_nombre_tercero',
        }

    def _handle_nombre_tercero_input(self, session, text):
        """Crea el partner del tercero y ejecuta la reserva."""
        name = (text or '').strip()
        if len(name) < 3:
            body = (
                '🔁 Por favor escribe el nombre completo del paciente '
                '(mínimo 3 caracteres).'
            )
            session.append_message(role='assistant', content=body)
            return {
                'response_text': body,
                'session_state': session.state,
                'tool_calls': [],
                'meta_payload': None,
                '_rdcm_warnings': [],
                'fast_path': 'nombre_tercero_invalid',
            }
        Partner = self.env['res.partner'].sudo()
        partner = Partner.create({
            'name': name,
            'vat': session.pending_third_party_cedula or False,
            'company_id': session.company_id.id,
            'comment': (
                f'Origen: agente WhatsApp (reservado por '
                f'{session.partner_id.name if session.partner_id else session.wa_from})'
            ),
        })
        session.pending_third_party_cedula = False
        return self._do_reserve_with_partner(session, partner.id)

    def _has_active_appointments(self, partner):
        """¿El partner tiene citas activas (reserved o confirmed)?"""
        if not partner:
            return False
        return bool(self.env['innatum.agenda.turno'].sudo().search_count([
            ('partner_id', '=', partner.id),
            ('state', 'in', ('reserved', 'confirmed')),
            ('company_id', '=', self.env.company.id),
        ]))

    def _show_main_menu(self, session, partner):
        """Saludo personalizado + menú principal (1 o 4 opciones según
        si tiene citas activas).
        """
        session.action_set_state('menu_principal')
        has_active = self._has_active_appointments(partner)
        nombre = partner.name.split(' ')[0] if partner.name else 'cliente'

        if has_active:
            body = (
                f'¡Hola {nombre}! 👋 Tienes citas activas con nosotros. '
                f'¿En qué te puedo ayudar?'
            )
            # 4 opciones → lista interactiva (max 3 botones en Meta)
            sections = [{
                'title': 'Opciones',
                'rows': [
                    {'id': 'menu:agendar', 'title': '1. Agendar cita',
                     'description': 'Reservar una nueva cita'},
                    {'id': 'menu:info', 'title': '2. Info de mis citas',
                     'description': 'Ver detalles de tus citas activas'},
                    {'id': 'menu:reagendar', 'title': '3. Reagendar',
                     'description': 'Cambiar fecha/hora de una cita'},
                    {'id': 'menu:cancelar', 'title': '4. Cancelar cita',
                     'description': 'Cancelar una cita activa'},
                ],
            }]
            payload = self._payload_list(
                session.wa_from,
                header='🏷️ Menú principal',
                body=body,
                button_text='Ver opciones',
                sections=sections,
            )
        else:
            body = (
                f'¡Hola {nombre}! 👋 ¿En qué te puedo ayudar?'
            )
            payload = self._payload_buttons(
                session.wa_from,
                header='🏷️ Menú principal',
                body=body,
                buttons=[
                    {'id': 'menu:agendar', 'title': '1. Agendar cita'},
                ],
            )

        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': payload,
            '_rdcm_warnings': [],
            'fast_path': 'menu_main',
        }

    def _start_agendar_flow(self, session):
        """Cliente eligió 'Agendar' → mostrar lista de servicios."""
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        result = Primitives.list_services(company=session.company_id)
        tool_summary = {
            'tool': 'consultar_servicios',
            'input': {},
            'result': result,
        }
        return self._fast_path_response(session, tool_summary, 'menu:agendar')

    def _show_my_appointments(self, session, mode='info'):
        """Lista las citas activas del cliente.

        mode: 'info' (solo lectura), 'reagendar', 'cancelar'.
        """
        if not session.partner_id:
            return self._text_response(session, '❌ No tengo tus datos. Vamos a empezar de nuevo.')

        Tools = self.env['flow.scheduling.tools']
        result = Tools.consultar_mis_citas(
            {'partner_id': session.partner_id.id, 'solo_activas': True},
            session=session,
        )
        citas = result.get('citas', [])
        if not citas:
            return self._text_response(
                session,
                '📭 No tienes citas activas en este momento. Si quieres '
                'agendar una nueva, escribe "agendar".',
            )

        mode_label = {
            'info': '📋 Mis citas',
            'reagendar': '📅 Reagendar — elige cuál',
            'cancelar': '❌ Cancelar — elige cuál',
        }.get(mode, '📋 Mis citas')

        body = {
            'info': 'Estas son tus citas activas. Toca una para ver el detalle.',
            'reagendar': '¿Cuál cita deseas reagendar?',
            'cancelar': '¿Cuál cita deseas cancelar?',
        }.get(mode, 'Tus citas:')

        id_prefix = {
            'info': 'info_turno',
            'reagendar': 'reagendar_turno',
            'cancelar': 'cancel_turno',
        }.get(mode, 'info_turno')

        rows = []
        for c in citas[:10]:
            rows.append({
                'id': f"{id_prefix}:{c['turno_id']}",
                'title': f"{c['fecha'][:12]} {c['hora']}",
                'description': f"{c['servicio']} · {c['state_label']}",
            })
        payload = self._payload_list(
            session.wa_from,
            header=mode_label,
            body=body,
            button_text='Ver citas',
            sections=[{'title': 'Citas activas', 'rows': rows}],
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [{'tool': 'consultar_mis_citas', 'input': {}, 'result': result}],
            'meta_payload': payload,
            '_rdcm_warnings': [],
            'fast_path': f'menu:{mode}',
        }

    def _show_turno_info(self, session, turno_id):
        """Muestra info detallada de un turno + botones de acción."""
        turno = self.env['innatum.agenda.turno'].sudo().browse(turno_id)
        if not turno.exists() or turno.partner_id.id != (session.partner_id.id if session.partner_id else 0):
            return self._text_response(session, '❌ No encontré esa cita.')
        import pytz
        dt_local = pytz.UTC.localize(turno.date_start).astimezone(pytz.timezone('America/Guayaquil'))
        state_label = {
            'reserved': 'Reservada (pendiente confirmar)',
            'confirmed': 'Confirmada',
            'done': 'Finalizada',
            'cancelled': 'Cancelada',
        }.get(turno.state, turno.state)
        body = (
            f"📋 *Detalle de cita*\n\n"
            f"Ref: {turno.name}\n"
            f"Servicio: {(turno.servicio_id.name if turno.servicio_id else '-')}\n"
            f"Profesional: {turno.professional_id.name}\n"
            f"Fecha: {dt_local.strftime('%A %d/%m/%Y')}\n"
            f"Hora: {dt_local.strftime('%H:%M')}\n"
            f"Estado: {state_label}"
        )
        buttons = []
        if turno.state in ('reserved', 'confirmed'):
            buttons.append({'id': f'cancel_turno:{turno.id}', 'title': '❌ Cancelar'})
        buttons.append({'id': 'menu:agendar', 'title': '📅 Nueva cita'})
        payload = self._payload_buttons(
            session.wa_from,
            header='📋 Mi cita',
            body=body,
            buttons=buttons,
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': payload,
            '_rdcm_warnings': [],
            'fast_path': 'info_turno',
        }

    def _ask_cancel_confirmation(self, session, turno_id):
        """Pide confirmación antes de cancelar un turno."""
        turno = self.env['innatum.agenda.turno'].sudo().browse(turno_id)
        if not turno.exists() or turno.partner_id.id != (session.partner_id.id if session.partner_id else 0):
            return self._text_response(session, '❌ No encontré esa cita.')
        import pytz
        dt_local = pytz.UTC.localize(turno.date_start).astimezone(pytz.timezone('America/Guayaquil'))
        body = (
            f"¿Confirmas que deseas cancelar tu cita?\n\n"
            f"Ref: {turno.name}\n"
            f"Fecha: {dt_local.strftime('%A %d/%m/%Y')} a las {dt_local.strftime('%H:%M')}\n"
            f"Servicio: {(turno.servicio_id.name if turno.servicio_id else '-')}"
        )
        payload = self._payload_buttons(
            session.wa_from,
            header='⚠️ Confirmar cancelación',
            body=body,
            buttons=[
                {'id': f'confirm_cancel:{turno.id}', 'title': '✅ Sí, cancelar'},
                {'id': f'info_turno:{turno.id}', 'title': '🔙 No, regresar'},
            ],
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': payload,
            '_rdcm_warnings': [],
            'fast_path': 'ask_cancel',
        }

    def _execute_cancel(self, session, turno_id):
        """Cliente confirmó cancelación → ejecutar cancelar_turno."""
        Tools = self.env['flow.scheduling.tools']
        result = Tools.cancelar_turno(
            {'turno_id': turno_id, 'motivo': 'Cancelado por cliente vía WhatsApp'},
            session=session,
        )
        if result.get('error'):
            return self._text_response(
                session, f'⚠️ {result["error"]}',
            )
        # Cierre del flujo: limpiar contexto efímero
        session.pending_turno_id = False
        session.current_servicio_code = False
        body = (
            f"✅ Cita cancelada\n\n"
            f"Ref: {result.get('referencia', '')}\n"
            f"Fecha: {result.get('fecha', '')} a las {result.get('hora', '')}\n\n"
            f"Si quieres reservar otra cita, escribe \"agendar\"."
        )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [{'tool': 'cancelar_turno', 'input': {'turno_id': turno_id}, 'result': result}],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'execute_cancel',
        }

    def _ask_for_cedula(self, session, first_time=False):
        """Pide la cédula al cliente nuevo."""
        if first_time:
            body = (
                '✏️ Para empezar, ¿me indicas tu número de cédula? '
                '(10 dígitos)'
            )
        else:
            body = (
                '🔁 Por favor, ingresa nuevamente tu cédula (10 dígitos válidos).'
            )
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'ask_cedula',
        }

    def _text_response(self, session, body):
        """Helper para devolver una respuesta de texto plano."""
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': None,
            '_rdcm_warnings': [],
            'fast_path': 'text',
        }

    def _fast_path_response(self, session, tool_summary, label):
        """Helper compartido: arma meta_payload + persiste body + devuelve dict."""
        meta_payload = None
        try:
            meta_payload = self._build_meta_interactive(
                [tool_summary], session.wa_from, response_text='',
            )
        except Exception:
            _logger.exception('Fast-path %s: fallo armando meta_payload', label)
        body_short = (
            meta_payload.get('interactive', {}).get('body', {}).get('text', '')
            if meta_payload else ''
        )
        session.append_message(
            role='assistant', content=body_short or '(interactive)',
        )
        return {
            'response_text': body_short,
            'session_state': session.state,
            'tool_calls': [tool_summary],
            'meta_payload': meta_payload,
            '_rdcm_warnings': [],
            'fast_path': label,
        }

    # -------------------------------------------------------------------------

    def _maybe_parse_structured(self, text):
        """Intenta parsear text como JSON. Devuelve dict o None."""
        if not text:
            return None
        stripped = text.strip()
        if not (stripped.startswith('{') and stripped.endswith('}')):
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    # -------------------------------------------------------------------------
    # Interactive messages (Meta WhatsApp Cloud API)
    # -------------------------------------------------------------------------

    def _build_meta_interactive(self, tool_calls_summary, wa_to, response_text=None):
        """Analiza el último tool_call exitoso para construir un meta_payload
        interactive (botones o lista) listo para enviar a Meta API.

        El `response_text` del LLM se usa como `body` del interactive cuando
        sea apropiado — así el cliente ve la descripción del LLM (no un
        placeholder hardcoded como "Elegí un servicio:").

        Returns:
          dict con el payload de Meta listo, o None si conviene texto plano.
        """
        if not tool_calls_summary or not wa_to:
            return None

        for call in reversed(tool_calls_summary):
            name = call.get('tool')
            res = call.get('result') or {}
            if 'error' in res:
                continue

            payload = self._payload_from_tool_result(name, res, wa_to, response_text)
            if payload:
                return payload

        return None

    def _payload_from_tool_result(self, name, res, wa_to, response_text=None):
        """Mapea un tool_result a un payload Meta. Devuelve None si no aplica."""

        # Bodies cortos hardcoded. NO usamos response_text del LLM como body
        # porque el LLM tiende a listar lo que ya está en los botones/lista
        # → redundante y satura el mensaje.

        # consultar_servicios → especialidades
        if name == 'consultar_servicios':
            items = res.get('especialidades') or []
            if not items:
                return None
            if len(items) <= 3:
                return self._payload_buttons(
                    wa_to,
                    header='🏷️ Servicios',
                    body='¿Qué servicio te interesa reservar?',
                    buttons=[
                        {'id': f"servicio:{i['code']}", 'title': i['name']}
                        for i in items
                    ],
                )
            return self._payload_list(
                wa_to,
                header='🏷️ Servicios disponibles',
                body='¿Qué servicio te interesa reservar?',
                button_text='Ver servicios',
                sections=[{
                    'title': 'Especialidades',
                    'rows': [
                        {
                            'id': f"servicio:{i['code']}",
                            'title': i['name'],
                            'description': '',
                        }
                        for i in items[:10]
                    ],
                }],
            )

        # consultar_regimen_servicio → fechas próximas
        if name == 'consultar_regimen_servicio':
            items = res.get('proximas_fechas_con_cupo') or []
            if not items:
                return None
            servicio = res.get('servicio', '')[:25]
            body_text = (
                'En la lista están las próximas fechas con cupo. '
                'Si prefieres otra fecha (ej. "el 27 de mayo"), escríbeme.'
            )
            if len(items) <= 3:
                return self._payload_buttons(
                    wa_to,
                    header=f'📅 {servicio}',
                    body=body_text,
                    buttons=[
                        {'id': f"fecha:{i['fecha_iso']}", 'title': i['fecha_label']}
                        for i in items
                    ],
                )
            return self._payload_list(
                wa_to,
                header=f'📅 {servicio}',
                body=body_text,
                button_text='Ver fechas',
                sections=[{
                    'title': 'Fechas con cupo',
                    'rows': [
                        {
                            'id': f"fecha:{i['fecha_iso']}",
                            'title': i['fecha_label'],
                            'description': f"{i['cupos']} cupo(s)",
                        }
                        for i in items[:10]
                    ],
                }],
            )

        # buscar_horarios_disponibles → slots (idealmente con fecha)
        if name == 'buscar_horarios_disponibles':
            slots = res.get('slots') or []
            if not slots:
                return None

            total = res.get('total_disponibles', len(slots))
            periodo_filtrado = res.get('periodo')  # 'AM' / 'PM' / None
            fecha_label = slots[0].get('fecha', '') if slots else ''
            fecha_iso = slots[0].get('fecha_iso', '')
            servicio_cod = slots[0].get('servicio_codigo', '')

            # CASO 1: cliente NO eligió período aún, hay >10 slots → botones
            # de embudo con los períodos que tienen cupos.
            if not periodo_filtrado and total > 10:
                total_am = res.get('total_am', 0)
                total_pm = res.get('total_pm', 0)
                total_night = res.get('total_night', 0)
                buttons = []
                if total_am:
                    buttons.append({
                        'id': f"periodo:AM:{servicio_cod}:{fecha_iso}",
                        'title': f'☀️ Mañana ({total_am})',
                    })
                if total_pm:
                    buttons.append({
                        'id': f"periodo:PM:{servicio_cod}:{fecha_iso}",
                        'title': f'🌤️ Tarde ({total_pm})',
                    })
                if total_night:
                    buttons.append({
                        'id': f"periodo:NIGHT:{servicio_cod}:{fecha_iso}",
                        'title': f'🌙 Noche ({total_night})',
                    })
                if len(buttons) < 3:
                    buttons.append({
                        'id': 'menu:otra_fecha',
                        'title': '📅 Otra fecha',
                    })
                return self._payload_buttons(
                    wa_to,
                    header=f'🕐 {fecha_label}',
                    body=(
                        f'Hay {total} turnos disponibles. '
                        f'¿En qué horario te interesa?'
                    ),
                    buttons=buttons[:3],
                )

            # CASO 2: cliente eligió período → lista plana del período.
            if periodo_filtrado:
                period_label = {
                    'AM': '☀️ Mañana',
                    'PM': '🌤️ Tarde',
                    'NIGHT': '🌙 Noche',
                }.get(periodo_filtrado, periodo_filtrado)
                return self._payload_list(
                    wa_to,
                    header=f'{period_label} — {fecha_label}',
                    body='Estos son los horarios disponibles:',
                    button_text='Ver horarios',
                    sections=[{
                        'title': period_label,
                        'rows': [
                            {
                                'id': f"turno:{s['turno_id']}",
                                'title': s['hora'],
                                'description': f"con {s['professional']}",
                            }
                            for s in slots[:10]
                        ],
                    }],
                )

            # CASO 3: hay fecha y ≤10 slots → lista con secciones AM/PM/Noche
            grouped = res.get('agrupado_por_periodo')
            if grouped:
                sections = []
                for key, label in (('AM', '☀️ Mañana'),
                                   ('PM', '🌤️ Tarde'),
                                   ('NIGHT', '🌙 Noche')):
                    rows = grouped.get(key) or []
                    if rows:
                        sections.append({
                            'title': label,
                            'rows': [
                                {
                                    'id': f"turno:{s['turno_id']}",
                                    'title': s['hora'],
                                    'description': f"con {s['professional']}",
                                }
                                for s in rows
                            ],
                        })
                if sections:
                    return self._payload_list(
                        wa_to,
                        header=f'🕐 {fecha_label}',
                        body='Estos son los horarios disponibles:',
                        button_text='Ver horarios',
                        sections=sections,
                    )

            # CASO 4 (fallback): sin fecha → lista plana truncada
            return self._payload_list(
                wa_to,
                header='🕐 Horarios disponibles',
                body='Estos son los horarios disponibles:',
                button_text='Ver horarios',
                sections=[{
                    'title': 'Próximos turnos',
                    'rows': [
                        {
                            'id': f"turno:{s['turno_id']}",
                            'title': f"{s['fecha'][:12]} {s['hora']}",
                            'description': f"con {s['professional']}",
                        }
                        for s in slots[:10]
                    ],
                }],
            )

        # reservar_turno éxito → resumen completo SIN botones (texto plano).
        # Si el cliente quiere reagendar/cancelar/hablar con humano, debe
        # escribir nuevamente al agente. Devolvemos None → endpoint envía
        # response_text como mensaje de texto normal.
        if name == 'reservar_turno' and res.get('exito'):
            return None

        return None

    def _payload_buttons(self, wa_to, header, body, buttons):
        """Construye payload Meta type=interactive button (max 3 botones)."""
        return {
            'messaging_product': 'whatsapp',
            'to': wa_to,
            'type': 'interactive',
            'interactive': {
                'type': 'button',
                'header': {'type': 'text', 'text': (header or '')[:60]},
                'body': {'text': (body or '')[:1024]},
                'action': {
                    'buttons': [
                        {
                            'type': 'reply',
                            'reply': {
                                'id': str(b['id'])[:256],
                                'title': str(b['title'])[:20],
                            },
                        }
                        for b in (buttons or [])[:3]
                    ],
                },
            },
        }

    def _payload_list(self, wa_to, header, body, button_text, sections):
        """Construye payload Meta type=interactive list.

        Límites de Meta Cloud API:
          - Max 10 SECCIONES
          - Max 10 ROWS TOTAL entre todas las secciones (NO 10 por sección)
          - title row: max 24 chars; description: max 72; id: 200
        """
        MAX_TOTAL_ROWS = 10
        safe_sections = []
        remaining = MAX_TOTAL_ROWS
        for sec in (sections or [])[:10]:
            if remaining <= 0:
                break
            section_rows = (sec.get('rows') or [])[:remaining]
            if not section_rows:
                continue
            safe_sections.append({
                'title': str(sec.get('title', ''))[:24],
                'rows': [
                    {
                        'id': str(r['id'])[:200],
                        'title': str(r['title'])[:24],
                        'description': str(r.get('description', ''))[:72],
                    }
                    for r in section_rows
                ],
            })
            remaining -= len(section_rows)
        return {
            'messaging_product': 'whatsapp',
            'to': wa_to,
            'type': 'interactive',
            'interactive': {
                'type': 'list',
                'header': {'type': 'text', 'text': (header or '')[:60]},
                'body': {'text': (body or '')[:1024]},
                'action': {
                    'button': (button_text or 'Ver opciones')[:20],
                    'sections': safe_sections,
                },
            },
        }
