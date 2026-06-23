# -*- coding: utf-8 -*-
import base64
import json
import logging
import tempfile
import os

import requests as http_requests

from odoo import http, fields
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class ChatbotController(http.Controller):

    def _tenant_company(self):
        """Devuelve la company del tenant según el website actual.
        Aísla todos los queries del chatbot para que un visitante de
        cliente1.innatum.com no agende contra datos de cliente2.innatum.com.
        """
        return request.website.company_id

    def _get_openai_api_key(self):
        """Obtiene API key de OpenAI para Whisper STT.
        Providers son globales (Innatum los administra); no se filtra por
        company porque las API keys son del SaaS, no del tenant.
        """
        ICP = request.env['ir.config_parameter'].sudo()
        key = ICP.get_param('innatum_ai_web.stt_api_key')
        if key:
            return key
        provider = request.env['innatum.ai.provider'].sudo().search(
            [('provider_type', '=', 'openai'), ('active', '=', True)],
            limit=1,
        )
        if provider and provider.api_key:
            return provider.api_key
        return None

    def _get_provider(self):
        """Obtiene el proveedor configurado para el chatbot. Global a Innatum."""
        ICP = request.env['ir.config_parameter'].sudo()
        provider_id = ICP.get_param('innatum_ai_web.provider_id')
        if provider_id:
            provider = request.env['innatum.ai.provider'].sudo().browse(int(provider_id))
            if provider.exists() and provider.active:
                return provider
        return request.env['innatum.ai.provider'].sudo().get_default_provider()

    @http.route('/chatbot/start', type='json', auth='public', website=True)
    def start_session(self):
        """Crea sesión en estado pending_id (esperando identificación)."""
        try:
            provider = self._get_provider()
        except Exception as e:
            _logger.error('Chatbot: no provider configured: %s', e)
            return {'success': False, 'error': 'El chatbot no está disponible en este momento.'}

        company = self._tenant_company()
        # Nombre del agente: el MISMO bot_name configurado para WhatsApp en el
        # Perfil del Negocio (page Identidad). Fallback a "Asistente Virtual".
        profile = request.env['innatum.business.profile'].sudo().search(
            [('company_id', '=', company.id)], limit=1)
        agent_name = (profile.bot_name or '').strip() or 'Asistente Virtual'

        Session = request.env['innatum.ai.chatbot.session'].sudo()
        session = Session.create({
            'provider_id': provider.id,
            'company_id': company.id,
            'state': 'pending_id',
        })

        welcome = (
            f"¡Hola! Soy **{agent_name}**, asistente de **{company.name}**.\n\n"
            f"Para comenzar, por favor ingresa tu **número de identificación** o **correo electrónico**."
        )

        return {
            'success': True,
            'token': session.token,
            'welcome_message': welcome,
            'state': 'pending_id',
            'agent_name': agent_name,
        }

    @http.route('/chatbot/verify', type='json', auth='public', website=True)
    def verify_client(self, token, cedula):
        """Verifica identificación del cliente. Si existe como partner del
        tenant, activa la sesión."""
        if not token or not cedula:
            return {'success': False, 'error': 'Parámetros inválidos.'}

        cedula = cedula.strip()
        if not cedula or len(cedula) < 3:
            return {'success': False, 'error': 'Ingresa una identificación válida.'}

        company = self._tenant_company()
        Session = request.env['innatum.ai.chatbot.session'].sudo()
        session = Session.search([
            ('token', '=', token),
            ('state', 'in', ('pending_id', 'pending_register')),
            ('company_id', '=', company.id),
        ], limit=1)
        if not session:
            return {'success': False, 'error': 'session_expired'}

        # Resetear estado si venía de registro cancelado
        if session.state == 'pending_register':
            session.write({'state': 'pending_id', 'register_vat': False})

        # Buscar por VAT o email, restringido al tenant actual.
        Partner = request.env['res.partner'].sudo()
        partner = Partner.search([
            ('vat', '=', cedula),
            ('company_id', '=', company.id),
        ], limit=1)
        if not partner:
            partner = Partner.search([
                ('email', '=ilike', cedula),
                ('company_id', '=', company.id),
            ], limit=1)

        if not partner:
            # Guardar cédula en sesión y pasar a estado de registro
            session.write({
                'state': 'pending_register',
                'register_vat': cedula,
            })
            # Detectar si account está instalado para pedir más o menos campos
            has_account = bool(request.env['ir.module.module'].sudo().search([
                ('name', '=', 'account'),
                ('state', '=', 'installed'),
            ], limit=1))
            return {
                'success': True,
                'found': False,
                'needs_register': True,
                'has_account': has_account,
                'vat': cedula,
                'message': (
                    f'No encontramos el número **{cedula}** en nuestro sistema.\n\n'
                    f'¿Deseas registrarte para agendar tu turno?'
                ),
            }

        # Cliente encontrado — activar sesión
        session.write({
            'state': 'active',
            'partner_id': partner.id,
        })

        # Listar servicios con disponibilidad (solo del tenant)
        Servicio = request.env['innatum.agenda.servicio'].sudo()
        Turno = request.env['innatum.agenda.turno'].sudo()
        servicios = Servicio.search([('company_ids', 'in', [company.id])])

        svc_disponibles = []
        for s in servicios:
            tiene = Turno.search([
                ('servicio_ids', 'in', s.id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], limit=1)
            if tiene:
                svc_disponibles.append({'name': s.name, 'code': s.code})

        if svc_disponibles:
            msg = (
                f"¡Hola **{partner.name}**! Te he identificado correctamente.\n\n"
                f"¿Qué servicio necesitas?"
            )
        else:
            msg = (
                f"¡Hola **{partner.name}**! Te he identificado correctamente.\n\n"
                f"En este momento no hay turnos disponibles. "
                f"Por favor intenta más tarde."
            )

        return {
            'success': True,
            'found': True,
            'patient_name': partner.name,
            'message': msg,
            'especialidades': svc_disponibles,
        }

    @http.route('/chatbot/register', type='json', auth='public', website=True)
    def register_client(self, token, name, phone, email='', **kwargs):
        """Registra un nuevo cliente desde el chatbot y activa la sesión."""
        if not token or not name or not phone:
            return {'success': False, 'error': 'Nombre y teléfono son obligatorios.'}

        name = name.strip()
        phone = phone.strip()
        email = (email or '').strip()

        if not name or len(name) < 3:
            return {'success': False, 'error': 'Ingresa un nombre válido (mínimo 3 caracteres).'}

        company = self._tenant_company()
        Session = request.env['innatum.ai.chatbot.session'].sudo()
        session = Session.search([
            ('token', '=', token),
            ('state', '=', 'pending_register'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not session:
            return {'success': False, 'error': 'session_expired'}

        # Re-chequeo defensivo de duplicados dentro del tenant.
        Partner = request.env['res.partner'].sudo()
        vat = (session.register_vat or '').strip()
        existing = Partner.browse()
        if vat:
            existing = Partner.search([
                ('vat', '=', vat),
                ('company_id', '=', company.id),
            ], limit=1)
        if not existing and email:
            existing = Partner.search([
                ('email', '=ilike', email),
                ('company_id', '=', company.id),
            ], limit=1)

        vals = {
            'name': name,
            'vat': vat,
            'mobile': phone,
            'email': email,
            'company_id': company.id,
        }

        # Campos adicionales si vienen (cuando account está instalado)
        street = kwargs.get('street', '').strip()
        city = kwargs.get('city', '').strip()
        country_id = kwargs.get('country_id')
        state_id = kwargs.get('state_id')

        if street:
            vals['street'] = street
        if city:
            vals['city'] = city
        if country_id:
            try:
                vals['country_id'] = int(country_id)
            except (ValueError, TypeError):
                pass
        if state_id:
            try:
                vals['state_id'] = int(state_id)
            except (ValueError, TypeError):
                pass

        try:
            if existing:
                # Reusar el contacto, completando los campos vacíos sin
                # pisar datos válidos previos.
                update = {}
                if not existing.mobile and not existing.phone and phone:
                    update['mobile'] = phone
                if not existing.email and email:
                    update['email'] = email
                if street and not existing.street:
                    update['street'] = street
                if city and not existing.city:
                    update['city'] = city
                if update:
                    existing.write(update)
                partner = existing
            else:
                partner = Partner.create(vals)
        except ValidationError as e:
            _logger.info('Chatbot register: constraint dispara: %s', e)
            return {
                'success': False,
                'error': str(e.args[0]) if e.args else (
                    'Ya existe un contacto con esa identificación.'
                ),
            }
        except Exception as e:
            _logger.error('Chatbot register error: %s', str(e))
            return {'success': False, 'error': 'No se pudo crear el registro. Intenta de nuevo.'}

        # Activar sesión
        session.write({
            'state': 'active',
            'partner_id': partner.id,
            'register_vat': False,
        })

        # Listar servicios con disponibilidad (solo del tenant)
        Servicio = request.env['innatum.agenda.servicio'].sudo()
        Turno = request.env['innatum.agenda.turno'].sudo()
        servicios = Servicio.search([('company_ids', 'in', [company.id])])

        svc_disponibles = []
        for s in servicios:
            tiene = Turno.search([
                ('servicio_ids', 'in', s.id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], limit=1)
            if tiene:
                svc_disponibles.append({'name': s.name, 'code': s.code})

        return {
            'success': True,
            'patient_name': partner.name,
            'message': f'¡Bienvenido/a **{partner.name}**! Te hemos registrado correctamente.\n\n¿Qué servicio necesitas?',
            'especialidades': svc_disponibles,
        }

    @http.route('/chatbot/send', type='json', auth='public', website=True)
    def send_message(self, token, message):
        """Procesa mensaje con IA. Solo funciona si la sesión está activa."""
        if not token or not message:
            return {'success': False, 'error': 'Parámetros inválidos.'}

        message = message.strip()
        if not message:
            return {'success': False, 'error': 'El mensaje no puede estar vacío.'}

        if len(message) > 1000:
            return {'success': False, 'error': 'El mensaje es demasiado largo (máximo 1000 caracteres).'}

        company = self._tenant_company()
        Session = request.env['innatum.ai.chatbot.session'].sudo()
        session = Session.search([
            ('token', '=', token),
            ('state', '=', 'active'),
            ('company_id', '=', company.id),
        ], limit=1)

        if not session:
            return {'success': False, 'error': 'session_expired'}

        if not session.partner_id:
            return {'success': False, 'error': 'Debes identificarte primero.'}

        if session.message_count >= session.MAX_MESSAGES:
            session.state = 'limit'
            return {
                'success': False,
                'error': 'Has alcanzado el límite de mensajes. Por favor inicia una nueva conversación.',
            }

        try:
            # Inyectamos la company del tenant en el contexto para que los
            # tool calls del engine (search de servicios/turnos) respeten
            # el aislamiento multi-tenant.
            engine = request.env['innatum.ai.chatbot'].sudo().with_company(company)
            result = engine.process_message(session, message)
            return {
                'success': True,
                'response': result['text'],
                'ui': result.get('ui', {}),
                'session_state': session.state,
            }
        except Exception as e:
            _logger.error('Chatbot error: %s', str(e), exc_info=True)
            return {
                'success': False,
                'error': 'Hubo un error procesando tu mensaje. Intenta de nuevo.',
            }

    @http.route('/chatbot/action', type='json', auth='public', website=True)
    def handle_action(self, token, action, **kwargs):
        """Ejecuta acciones determinísticas sin IA. Ahorra tokens."""
        if not token or not action:
            return {'success': False, 'error': 'Parámetros inválidos.'}

        company = self._tenant_company()
        Session = request.env['innatum.ai.chatbot.session'].sudo()
        session = Session.search([
            ('token', '=', token),
            ('state', '=', 'active'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not session:
            return {'success': False, 'error': 'session_expired'}

        # Engine corre con company del tenant para que los tool calls
        # filtren naturalmente vía record rules multi-company.
        engine = request.env['innatum.ai.chatbot'].sudo().with_company(company)

        try:
            if action == 'list_specialties':
                return self._action_list_services(engine, session)
            elif action == 'select_specialty':
                return self._action_select_service(engine, session, kwargs.get('code', ''))
            elif action == 'select_professional':
                return self._action_select_professional(engine, session, kwargs.get('name', ''), kwargs.get('specialty_code', ''))
            elif action == 'confirm_slot':
                return self._action_confirm_slot(
                    engine, session,
                    kwargs.get('turno_id'),
                    kwargs.get('servicio_codigo') or '',
                )
            else:
                return {'success': False, 'error': f'Acción desconocida: {action}'}
        except Exception as e:
            _logger.error('Chatbot action %s error: %s', action, str(e), exc_info=True)
            error_msg = str(e)
            if 'ya no está disponible' in error_msg or 'no existe' in error_msg:
                return {'success': False, 'error': error_msg}
            return {'success': False, 'error': 'Hubo un error. Intenta de nuevo.'}

    def _inject_history(self, session, user_msg, assistant_msg):
        """Inyecta mensajes sintéticos al historial para mantener contexto."""
        messages = json.loads(session.api_messages or '[]')
        messages.append({'role': 'user', 'content': user_msg})
        messages.append({'role': 'assistant', 'content': assistant_msg})
        session.write({
            'api_messages': json.dumps(messages, ensure_ascii=False, default=str),
            'message_count': session.message_count + 1,
        })

    def _action_list_services(self, engine, session):
        result = engine._tool_listar_servicios({})
        especialidades = result.get('especialidades', [])

        if not especialidades:
            msg = 'No hay servicios con disponibilidad en este momento.'
            self._inject_history(session, 'Quiero ver los servicios', msg)
            return {'success': True, 'response': msg, 'ui': {}}

        msg = '¿Qué servicio necesitas?'
        names = ', '.join(e['name'] for e in especialidades)
        self._inject_history(session, 'Quiero ver los servicios',
                             f'Los servicios disponibles son: {names}. ¿Cuál necesitas?')
        return {
            'success': True,
            'response': msg,
            'ui': {'especialidades': especialidades},
            'session_state': session.state,
        }

    def _action_select_service(self, engine, session, code):
        if not code:
            return {'success': False, 'error': 'Código de servicio requerido.'}

        company = self._tenant_company()
        servicio = request.env['innatum.agenda.servicio'].sudo().search([
            ('code', '=ilike', code),
            ('company_ids', 'in', [company.id]),
        ], limit=1)
        service_name = servicio.name if servicio else code

        result = engine._tool_listar_profesionales({'servicio': code})
        profesionales = result.get('professionals', [])

        if not profesionales:
            msg = f'No hay profesionales con disponibilidad para {service_name} en este momento.'
            self._inject_history(session, f'Quiero {service_name}', msg)
            return {'success': True, 'response': msg, 'ui': {}}

        ui = {}
        if len(profesionales) == 1:
            prof = profesionales[0]
            slots_result = engine._tool_buscar_disponibilidad({
                'servicio': code,
                'profesional_nombre': prof['nombre'],
            })
            slots = slots_result.get('slots', [])
            if slots:
                msg = f'El profesional disponible es **{prof["nombre"]}**. Encontré {len(slots)} horarios disponibles. Selecciona el que prefieras:'
                ui['slots'] = slots
                ui['especialidad'] = service_name
            else:
                msg = f'El profesional disponible es **{prof["nombre"]}** pero no tiene horarios disponibles próximamente.'

            self._inject_history(session, f'Quiero {service_name}',
                                 f'El profesional disponible para {service_name} es {prof["nombre"]}. '
                                 f'Se encontraron {len(slots)} horarios disponibles.')
        else:
            msg = f'Los profesionales disponibles para **{service_name}** son:'
            ui['professionals'] = profesionales
            ui['specialty_code'] = code

            prof_names = ', '.join(d['nombre'] for d in profesionales)
            self._inject_history(session, f'Quiero {service_name}',
                                 f'Los profesionales disponibles para {service_name} son: {prof_names}. ¿Con cuál prefieres?')

        return {
            'success': True,
            'response': msg,
            'ui': ui,
            'session_state': session.state,
        }

    def _action_select_professional(self, engine, session, prof_name, service_code):
        if not prof_name or not service_code:
            return {'success': False, 'error': 'Nombre del profesional y servicio requeridos.'}

        result = engine._tool_buscar_disponibilidad({
            'servicio': service_code,
            'profesional_nombre': prof_name,
        })
        slots = result.get('slots', [])
        service_name = result.get('especialidad', service_code)

        if not slots:
            msg = f'No hay horarios disponibles para **{prof_name}** en este momento.'
            self._inject_history(session, f'Quiero agendar con {prof_name}', msg)
            return {'success': True, 'response': msg, 'ui': {}}

        msg = f'Encontré {len(slots)} horarios disponibles con **{prof_name}**. Selecciona el que prefieras:'
        self._inject_history(session, f'Quiero agendar con {prof_name}',
                             f'Se encontraron {len(slots)} horarios disponibles con {prof_name} en {service_name}.')

        return {
            'success': True,
            'response': msg,
            'ui': {'slots': slots, 'especialidad': service_name},
            'session_state': session.state,
        }

    def _action_confirm_slot(self, engine, session, turno_id, servicio_codigo=''):
        if not turno_id:
            return {'success': False, 'error': 'ID de turno requerido.'}

        params = {'turno_id': int(turno_id)}
        if servicio_codigo:
            params['servicio_codigo'] = servicio_codigo
        result = engine._tool_reservar_turno(params, session=session)

        if result.get('error'):
            self._inject_history(session, f'Confirmo turno {turno_id}', result['error'])
            return {'success': True, 'response': result['error'], 'ui': {}}

        booking = {
            'referencia': result.get('referencia'),
            'especialidad': result.get('especialidad'),
            'professional': result.get('professional'),
            'fecha': result.get('fecha'),
            'hora': result.get('hora'),
            'paciente': result.get('paciente'),
        }

        company = self._tenant_company()
        turno = request.env['innatum.agenda.turno'].sudo().search([
            ('name', '=', result.get('referencia')),
            ('company_id', '=', company.id),
        ], limit=1)
        if turno:
            session.write({
                'turno_id': turno.id,
                'partner_id': turno.partner_id.id,
                'state': 'done',
            })

        msg = f'¡Cita reservada exitosamente! Tu cita de **{result["especialidad"]}** con **{result["professional"]}** es el **{result["fecha"]}** a las **{result["hora"]}**.'
        self._inject_history(session, f'Confirmo la cita (turno {turno_id})', msg)

        return {
            'success': True,
            'response': msg,
            'ui': {'booking': booking},
            'session_state': 'done',
        }

    @http.route('/chatbot/transcribe', type='json', auth='public', website=True)
    def transcribe_audio(self, token, audio_base64):
        """Transcribe audio usando OpenAI Whisper API."""
        if not token or not audio_base64:
            return {'success': False, 'error': 'Parámetros inválidos.'}

        company = self._tenant_company()
        Session = request.env['innatum.ai.chatbot.session'].sudo()
        session = Session.search([
            ('token', '=', token),
            ('state', 'in', ('pending_id', 'active')),
            ('company_id', '=', company.id),
        ], limit=1)
        if not session:
            return {'success': False, 'error': 'session_expired'}

        api_key = self._get_openai_api_key()
        if not api_key:
            _logger.error('Chatbot STT: no OpenAI API key configured')
            return {
                'success': False,
                'error': 'La función de voz no está disponible en este momento.',
            }

        try:
            audio_bytes = base64.b64decode(audio_base64)
        except Exception:
            return {'success': False, 'error': 'Audio inválido.'}

        if len(audio_bytes) > 10 * 1024 * 1024:
            return {'success': False, 'error': 'El audio es demasiado largo.'}

        if len(audio_bytes) < 1000:
            return {'success': False, 'error': 'No se detectó audio. Intenta de nuevo.'}

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            resp = http_requests.post(
                'https://api.openai.com/v1/audio/transcriptions',
                headers={'Authorization': f'Bearer {api_key}'},
                data={
                    'model': 'whisper-1',
                    'language': 'es',
                    'response_format': 'text',
                },
                files={'file': ('audio.webm', open(tmp_path, 'rb'), 'audio/webm')},
                timeout=30,
            )

            if resp.status_code != 200:
                _logger.error('Whisper API error %s: %s', resp.status_code, resp.text)
                return {'success': False, 'error': 'No se pudo transcribir el audio.'}

            text = resp.text.strip()
            if not text:
                return {'success': False, 'error': 'No se detectó voz en el audio. Intenta de nuevo.'}

            return {'success': True, 'text': text}

        except http_requests.Timeout:
            return {'success': False, 'error': 'Tiempo de espera agotado.'}
        except Exception as e:
            _logger.error('Chatbot STT error: %s', str(e), exc_info=True)
            return {'success': False, 'error': 'Error al procesar el audio.'}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
