# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsappWebhookController(http.Controller):
    """Endpoint que n8n llama tras resolver el tenant.

    Fase 1B: invoca al `innatum.whatsapp.agent` para procesar el mensaje.
    Si `agent_enabled` está apagado en la BD, vuelve a comportamiento echo
    (útil para debug del transporte sin gastar tokens IA).
    """

    @http.route(
        '/api/whatsapp/message',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def receive_message(self, **_kwargs):
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'innatum_ai_core.n8n_shared_secret')
        provided = request.httprequest.headers.get('X-Innatum-Token')
        if not expected or provided != expected:
            return self._json(401, {'error': 'unauthorized'})

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except json.JSONDecodeError:
            return self._json(400, {'error': 'invalid_json'})

        phone_number_id = payload.get('phone_number_id')
        wa_from = payload.get('wa_from')
        text = payload.get('text') or ''
        message_type = payload.get('message_type', 'text')
        media_id = payload.get('media_id') or ''
        wamid = payload.get('wamid') or ''

        if not phone_number_id or not wa_from:
            return self._json(400, {'error': 'missing_required_fields'})

        company = request.env['res.company'].sudo().search([
            ('wa_phone_number_id', '=', phone_number_id),
        ], limit=1)
        if not company:
            _logger.warning(
                'Phone number id %s not mapped to any company', phone_number_id)
            return self._json(404, {'error': 'tenant_not_found'})

        # User dedicado del agente: garantiza trazabilidad (create_uid/write_uid)
        # y permisos quirúrgicos (rol Operador de Agenda). Si no existe se crea
        # lazy en la primera llamada.
        # `with_company` es método de recordset, no de Environment. Para fijar
        # la company del request usamos el context `allowed_company_ids`.
        wa_user = company.sudo().ensure_wa_agent_user()
        env = request.env(
            user=wa_user.id,
            su=False,
            context=dict(request.env.context, allowed_company_ids=[company.id]),
        )

        session = env['innatum.ai.session'].sudo().get_or_create(
            company=company, wa_from=wa_from,
        )

        agent_enabled = request.env['ir.config_parameter'].sudo().get_param(
            'innatum_ai_core.agent_enabled', '1') == '1'

        if agent_enabled:
            try:
                result = env['innatum.whatsapp.agent'].process_message(
                    session=session,
                    text=text,
                    message_type=message_type,
                    media_id=media_id,
                    wamid=wamid,
                )
            except Exception:
                _logger.exception(
                    'Agent process_message crashed for session %s', session.id)
                return self._json(500, {
                    'session_id': session.id,
                    'session_state': session.state,
                    'response_text': 'Tuve un problema, intenta de nuevo en un momento.',
                    'error': 'agent_crash',
                })
        else:
            session.append_message(role='user', content=text, wamid=wamid)
            response_text = 'echo: %s' % text
            session.append_message(role='assistant', content=response_text)
            result = {
                'response_text': response_text,
                'session_state': session.state,
            }

        meta_payload = result.get('meta_payload')
        response_type = 'interactive' if meta_payload else 'text'

        # session_id_override permite que process_message reporte una nueva
        # sesión si hizo un auto-reset (ej. salida de handoff >2h).
        reported_session_id = result.get('session_id_override') or session.id
        # skip_send: si el response_text está vacío y no hay payload, le
        # decimos a n8n que NO intente enviar (evita 400 de Meta API).
        skip_send = bool(result.get('skip_send'))
        if not skip_send and not result.get('response_text') and not meta_payload:
            skip_send = True

        return self._json(200, {
            'session_id': reported_session_id,
            'previous_session_id': result.get('previous_session_id'),
            'session_state': result.get('session_state', session.state),
            'response_text': result.get('response_text', ''),
            'response_type': response_type,
            'meta_payload': meta_payload,
            'message_type_received': message_type,
            'tool_calls': result.get('tool_calls', []),
            'rdcm_warnings': result.get('_rdcm_warnings', []),
            'skip_send': skip_send,
        })

    @staticmethod
    def _json(status, body):
        return request.make_response(
            json.dumps(body),
            status=status,
            headers=[('Content-Type', 'application/json')],
        )
