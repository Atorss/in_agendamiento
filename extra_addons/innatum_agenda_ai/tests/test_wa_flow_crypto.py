# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

from ..models import wa_flow_crypto
from .common_wa_flow import meta_decrypt_response, meta_encrypt_request


class TestWaFlowCrypto(TransactionCase):
    """Round-trip criptográfico del Data Endpoint (protocolo Meta)."""

    def setUp(self):
        super().setUp()
        self.priv, self.pub = wa_flow_crypto.generate_keypair_pem()

    def test_keypair_es_rsa_2048_pem(self):
        self.assertIn('BEGIN PRIVATE KEY', self.priv)
        self.assertIn('BEGIN PUBLIC KEY', self.pub)

    def test_round_trip_request(self):
        body, aes_key, iv = meta_encrypt_request(
            {'action': 'ping', 'version': '3.0'}, self.pub)
        payload, got_key, got_iv = wa_flow_crypto.decrypt_request(
            body, self.priv)
        self.assertEqual(payload['action'], 'ping')
        self.assertEqual(got_key, aes_key)
        self.assertEqual(got_iv, iv)

    def test_round_trip_response_con_iv_invertido(self):
        body, aes_key, iv = meta_encrypt_request({'action': 'ping'}, self.pub)
        _, key, viv = wa_flow_crypto.decrypt_request(body, self.priv)
        b64 = wa_flow_crypto.encrypt_response(
            {'data': {'status': 'active'}}, key, viv)
        resp = meta_decrypt_response(b64, aes_key, iv)
        self.assertEqual(resp, {'data': {'status': 'active'}})

    def test_payload_corrupto_lanza_valueerror(self):
        body, _, _ = meta_encrypt_request({'action': 'ping'}, self.pub)
        body['encrypted_aes_key'] = body['encrypted_aes_key'][:-8] + 'AAAAAAA='
        with self.assertRaises(ValueError):
            wa_flow_crypto.decrypt_request(body, self.priv)

    def test_modelo_keypair_genera_y_restringe(self):
        company = self.env['res.company'].create({'name': 'KP Co'})
        kp = self.env['innatum.wa.flow.keypair'].create(
            {'company_id': company.id})
        kp.action_generate()
        self.assertIn('BEGIN PRIVATE KEY', kp.private_key_pem)
        self.assertIn('BEGIN PUBLIC KEY', kp.public_key_pem)
        # Unicidad por company
        with self.assertRaises(Exception), self.env.cr.savepoint():
            self.env['innatum.wa.flow.keypair'].create(
                {'company_id': company.id})
