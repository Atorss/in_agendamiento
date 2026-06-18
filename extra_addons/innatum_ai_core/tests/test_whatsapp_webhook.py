# -*- coding: utf-8 -*-
import json
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestWhatsappWebhook(HttpCase):

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': 'Test Tenant Webhook',
            'wa_phone_number_id': 'PHN_HOOK_TEST',
        })
        self.tmpl = self.env.ref('innatum_ai_core.vertical_template_odontologia')
        self.profile = self.env['innatum.business.profile'].create({
            'company_id': self.company.id,
            'vertical_template_id': self.tmpl.id,
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_ai_core.n8n_shared_secret', 'fase1a-test-secret')

    def _payload(self, wa_from, text, phone_number_id='PHN_HOOK_TEST',
                 message_type='text'):
        return {
            'phone_number_id': phone_number_id,
            'wa_from': wa_from,
            'message_type': message_type,
            'text': text,
        }

    def test_echo_basic(self):
        resp = self.url_open(
            '/api/whatsapp/message',
            data=json.dumps(self._payload('+593999000111', 'hola')),
            headers={
                'Content-Type': 'application/json',
                'X-Innatum-Token': 'fase1a-test-secret',
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['response_text'], 'echo: hola')
        self.assertIn('session_id', body)
        self.assertEqual(body['session_state'], 'nueva')

    def test_unknown_phone_number_id_returns_404(self):
        resp = self.url_open(
            '/api/whatsapp/message',
            data=json.dumps(self._payload(
                '+593999000111', 'hola', phone_number_id='UNKNOWN_PHN')),
            headers={
                'Content-Type': 'application/json',
                'X-Innatum-Token': 'fase1a-test-secret',
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_missing_token_returns_401(self):
        resp = self.url_open(
            '/api/whatsapp/message',
            data=json.dumps(self._payload('+593999000111', 'hola')),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_wrong_token_returns_401(self):
        resp = self.url_open(
            '/api/whatsapp/message',
            data=json.dumps(self._payload('+593999000111', 'hola')),
            headers={
                'Content-Type': 'application/json',
                'X-Innatum-Token': 'wrong-secret',
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_invalid_json_returns_400(self):
        resp = self.url_open(
            '/api/whatsapp/message',
            data='not json at all',
            headers={
                'Content-Type': 'application/json',
                'X-Innatum-Token': 'fase1a-test-secret',
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_required_fields_returns_400(self):
        resp = self.url_open(
            '/api/whatsapp/message',
            data=json.dumps({'phone_number_id': 'PHN_HOOK_TEST'}),
            headers={
                'Content-Type': 'application/json',
                'X-Innatum-Token': 'fase1a-test-secret',
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_session_created_on_first_message(self):
        self.url_open(
            '/api/whatsapp/message',
            data=json.dumps(self._payload('+593999000222', 'hola')),
            headers={
                'Content-Type': 'application/json',
                'X-Innatum-Token': 'fase1a-test-secret',
            },
        )
        session = self.env['innatum.ai.session'].search([
            ('company_id', '=', self.company.id),
            ('wa_from', '=', '+593999000222'),
        ], limit=1)
        self.assertTrue(session)
        self.assertEqual(len(session.message_ids), 2)
