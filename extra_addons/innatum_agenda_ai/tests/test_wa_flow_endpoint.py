# -*- coding: utf-8 -*-
import json

from odoo.tests.common import HttpCase

from .common_wa_flow import meta_decrypt_response, meta_encrypt_request


class TestWaFlowEndpoint(HttpCase):
    """Round-trip HTTP+cifrado del Data Endpoint (simulando a Meta)."""

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': 'Flow Tenant', 'agenda_modo': 'directa',
        })
        plan = self.env['in_agenda.plan'].create(
            {'name': 'Plan Flow', 'code': 'TEST_FLOW'})
        self.env['in_agenda.suscripcion'].create({
            'company_id': self.company.id, 'plan_id': plan.id,
            'fecha_fin': '2099-12-31', 'state': 'active'})
        self.operadora = self.env['hr.employee'].create({
            'name': 'Dra. Flow', 'company_id': self.company.id})
        self.servicio = self.env['innatum.agenda.servicio'].create({
            'name': 'Valoración', 'company_id': self.company.id,
            'duracion': 30.0, 'publicar_web': True,
            'operador_ids': [(6, 0, self.operadora.ids)]})
        self.kp = self.env['innatum.wa.flow.keypair'].create(
            {'company_id': self.company.id})
        self.kp.action_generate()
        self.session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id, 'wa_from': '593990001122'})
        from ..models.wa_flow_token import (get_flow_token_secret,
                                            make_flow_token)
        import time
        self.token = make_flow_token(
            self.session.id, get_flow_token_secret(self.env), time.time())
        self.url = '/whatsapp/flow/data/%s' % self.company.wa_flow_slug

    def _post(self, payload, url=None):
        body, aes_key, iv = meta_encrypt_request(
            payload, self.kp.public_key_pem)
        resp = self.url_open(
            url or self.url, data=json.dumps(body),
            headers={'Content-Type': 'application/json'})
        return resp, aes_key, iv

    def test_slug_se_autogenera(self):
        self.assertTrue(self.company.wa_flow_slug)

    def test_ping(self):
        resp, aes_key, iv = self._post(
            {'version': '3.0', 'action': 'ping'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(meta_decrypt_response(resp.text, aes_key, iv),
                         {'data': {'status': 'active'}, 'version': '3.0'})

    def test_respuesta_incluye_version(self):
        # data_api 3.0 exige `version` en el nivel superior; su ausencia
        # rompe el Flow publicado ("Se produjo un error").
        resp, aes_key, iv = self._post({
            'version': '3.0', 'action': 'INIT', 'flow_token': self.token})
        out = meta_decrypt_response(resp.text, aes_key, iv)
        self.assertEqual(out['version'], '3.0')

    def test_init_devuelve_fecha(self):
        resp, aes_key, iv = self._post({
            'version': '3.0', 'action': 'INIT',
            'flow_token': self.token})
        out = meta_decrypt_response(resp.text, aes_key, iv)
        self.assertEqual(out['screen'], 'FECHA')
        self.assertEqual(out['data']['servicio_code'], self.servicio.code)

    def test_token_invalido_da_error_sesion(self):
        resp, aes_key, iv = self._post({
            'version': '3.0', 'action': 'INIT', 'flow_token': 'ft1:9:9:x'})
        out = meta_decrypt_response(resp.text, aes_key, iv)
        self.assertEqual(out['screen'], 'ERROR_SESION')

    def test_slug_desconocido_404(self):
        resp, _, _ = self._post({'action': 'ping'},
                                url='/whatsapp/flow/data/nadie')
        self.assertEqual(resp.status_code, 404)

    def test_basura_da_421(self):
        resp = self.url_open(
            self.url, data=json.dumps({
                'encrypted_flow_data': 'QUFB', 'encrypted_aes_key': 'QUFB',
                'initial_vector': 'QUFB'}),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(resp.status_code, 421)

    def test_firma_invalida_401_si_secret_configurado(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_wa.flow_app_secret', 'app-secret-test')
        body, _, _ = meta_encrypt_request(
            {'action': 'ping'}, self.kp.public_key_pem)
        resp = self.url_open(
            self.url, data=json.dumps(body),
            headers={'Content-Type': 'application/json',
                     'X-Hub-Signature-256': 'sha256=deadbeef'})
        self.assertEqual(resp.status_code, 401)
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_wa.flow_app_secret', '')

    def test_token_de_otro_tenant_no_cruza(self):
        """Un flow_token de la sesión del tenant A contra el slug del
        tenant B debe dar ERROR_SESION: aislamiento multi-tenant."""
        otra = self.env['res.company'].create({
            'name': 'Otro Tenant', 'agenda_modo': 'directa'})
        kp2 = self.env['innatum.wa.flow.keypair'].create(
            {'company_id': otra.id})
        kp2.action_generate()
        url_b = '/whatsapp/flow/data/%s' % otra.wa_flow_slug
        body, aes_key, iv = meta_encrypt_request(
            {'version': '3.0', 'action': 'INIT',
             'flow_token': self.token},   # token del tenant A
            kp2.public_key_pem)           # cifrado para el tenant B
        resp = self.url_open(
            url_b, data=json.dumps(body),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(resp.status_code, 200)
        out = meta_decrypt_response(resp.text, aes_key, iv)
        self.assertEqual(out['screen'], 'ERROR_SESION')
