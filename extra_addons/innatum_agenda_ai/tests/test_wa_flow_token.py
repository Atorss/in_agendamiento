# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

from ..models.wa_flow_token import (
    TTL_SECONDS, check_flow_token, get_flow_token_secret, make_flow_token)

NOW = 1_800_000_000.0
SECRET = 'secreto-de-test'


class TestWaFlowToken(TransactionCase):

    def test_round_trip(self):
        tok = make_flow_token(42, SECRET, NOW)
        self.assertTrue(tok.startswith('ft1:42:'))
        self.assertEqual(check_flow_token(tok, SECRET, NOW + 60), 42)

    def test_expirado(self):
        tok = make_flow_token(42, SECRET, NOW)
        self.assertIsNone(check_flow_token(tok, SECRET, NOW + TTL_SECONDS + 1))

    def test_firma_invalida(self):
        tok = make_flow_token(42, SECRET, NOW)
        self.assertIsNone(check_flow_token(tok, 'otro-secreto', NOW))
        self.assertIsNone(check_flow_token(tok[:-1] + '0', SECRET, NOW))

    def test_formatos_basura(self):
        for t in ('', 'ft1:abc:1:2', 'x:1:2:3', 'ft1:1:2', None):
            self.assertIsNone(check_flow_token(t, SECRET, NOW), t)

    def test_secret_se_autogenera_y_persiste(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('innatum_wa.flow_token_secret', '')
        s1 = get_flow_token_secret(self.env)
        self.assertGreaterEqual(len(s1), 32)
        self.assertEqual(get_flow_token_secret(self.env), s1)

    def test_firma_no_ascii_devuelve_none(self):
        """El segmento de firma es input no confiable: no-ASCII no debe
        lanzar TypeError (contrato: basura → None, nunca excepción)."""
        tok = 'ft1:42:1800999999:' + 'ñ' * 64
        self.assertIsNone(check_flow_token(tok, SECRET, NOW))
