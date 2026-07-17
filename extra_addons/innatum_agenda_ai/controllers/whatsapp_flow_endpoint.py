# -*- coding: utf-8 -*-
"""Data Endpoint de WhatsApp Flows (spec §3.3/§4.1).

Transporte + criptografía; la lógica de pantallas vive en
innatum.wa.flow.agent. Códigos: 200 (base64 cifrado), 404 (slug),
421 (indescifrable o sin claves), 401 (firma inválida con app secret
configurado). Errores de negocio NUNCA devuelven 5xx: van como pantalla
ERROR_SESION dentro de la respuesta cifrada."""
import hashlib
import hmac
import json
import logging
import time

from odoo import http
from odoo.http import request

from ..models import wa_flow_crypto
from ..models.wa_flow_token import check_flow_token, get_flow_token_secret

_logger = logging.getLogger(__name__)


class WhatsappFlowEndpoint(http.Controller):

    @http.route('/whatsapp/flow/data/<string:slug>', type='http',
                auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def flow_data(self, slug, **_kwargs):
        env = request.env
        company = env['res.company'].sudo().search(
            [('wa_flow_slug', '=', slug)], limit=1)
        if not company:
            return request.make_response('not found', status=404)

        raw = request.httprequest.get_data()
        app_secret = env['ir.config_parameter'].sudo().get_param(
            'innatum_wa.flow_app_secret')
        if app_secret:
            expected = 'sha256=' + hmac.new(
                app_secret.encode(), raw, hashlib.sha256).hexdigest()
            provided = request.httprequest.headers.get(
                'X-Hub-Signature-256', '')
            if not hmac.compare_digest(expected, provided):
                return request.make_response('bad signature', status=401)

        keypair = env['innatum.wa.flow.keypair'].sudo().search(
            [('company_id', '=', company.id)], limit=1)
        if not keypair or not keypair.private_key_pem:
            return request.make_response('no keypair', status=421)

        try:
            body = json.loads(raw.decode() or '{}')
            payload, aes_key, iv = wa_flow_crypto.decrypt_request(
                body, keypair.private_key_pem)
        except (ValueError, json.JSONDecodeError):
            return request.make_response('cannot decrypt', status=421)

        # data_api 3.0 exige `version` en el nivel superior de CADA respuesta.
        # Su ausencia la tolera el Flow en borrador pero NO el publicado
        # ("Se produjo un error"). Eco de la versión que Meta manda.
        version = payload.get('version') or '3.0'
        action = payload.get('action')
        pdata = payload.get('data') or {}
        session = None
        if action == 'ping':
            resp = {'data': {'status': 'active'}}
        else:
            sid = check_flow_token(
                payload.get('flow_token'), get_flow_token_secret(env),
                time.time())
            session = env['innatum.ai.session'].sudo().browse(
                sid or 0).exists()
            if not session or session.company_id != company:
                resp = {'screen': 'ERROR_SESION', 'data': {'mensaje': (
                    'Tu sesión expiró. Cierra esta ventana y escribe '
                    '*hola* para agendar.')}}
                session = None
            else:
                resp = env['innatum.wa.flow.agent'].handle(
                    session, action, payload.get('screen'),
                    pdata, payload.get('flow_token'))

        resp['version'] = version
        # DEBUG temporal (Web vs móvil): volcamos el payload ENTRANTE completo
        # de Meta (token redactado) y la respuesta, para comparar qué manda
        # cada cliente en cada paso. El campo `screen` es el clave: en el ciclo
        # de WhatsApp Web llega SERVICIO cuando el usuario está en HORA.
        dbg_in = dict(payload)
        if dbg_in.get('flow_token'):
            dbg_in['flow_token'] = 'ft<redacted>'
        ua = request.httprequest.headers.get('User-Agent', '')
        _logger.info(
            'Flow endpoint slug=%s sid=%s partner=%s UA=%s IN=%s '
            'OUT_screen=%s OUT_data=%s',
            slug, session.id if session else None,
            session.partner_id.id if session else None, ua,
            json.dumps(dbg_in, ensure_ascii=False, default=str),
            resp.get('screen', 'ping'),
            json.dumps(resp.get('data') or {}, ensure_ascii=False,
                       default=str)[:600])
        out = wa_flow_crypto.encrypt_response(resp, aes_key, iv)
        return request.make_response(
            out, headers=[('Content-Type', 'text/plain')])
