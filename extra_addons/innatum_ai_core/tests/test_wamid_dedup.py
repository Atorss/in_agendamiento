# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestWamidDedup(TransactionCase):
    """Deduplicación por wamid en process_message.

    - Una reentrega del MISMO mensaje (mismo wamid) se descarta sin reprocesar.
    - Un texto idéntico con wamid DISTINTO se procesa normalmente: esto
      reproduce el bug en que un 'Hola' enviado horas después se silenciaba
      por compararse solo el texto del mensaje anterior.
    """

    def setUp(self):
        super().setUp()
        self.Agent = self.env['innatum.whatsapp.agent']
        self.company = self.env['res.company'].create({'name': 'Clínica Wamid'})
        self.partner = self.env['res.partner'].create({'name': 'John Doe'})
        self.session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id,
            'wa_from': '593996706629',
            'partner_id': self.partner.id,
        })
        self.session.action_set_state('menu_principal')

    def test_duplicate_wamid_is_skipped(self):
        # El mensaje con este wamid ya quedó registrado (reentrega de Meta).
        self.session.append_message(role='user', content='Hola', wamid='WAMID_X')
        res = self.Agent.process_message(self.session, 'Hola', wamid='WAMID_X')
        self.assertTrue(res.get('skip_send'))
        self.assertEqual(res.get('fast_path'), 'dup_wamid')

    def test_same_text_new_wamid_is_processed(self):
        # Primer 'Hola' (wamid 1): el agente debe responder con el menú.
        res1 = self.Agent.process_message(self.session, 'Hola', wamid='WAMID_1')
        self.assertFalse(res1.get('skip_send'))
        self.assertTrue(res1.get('meta_payload'))
        # Segundo 'Hola' idéntico pero con wamid distinto (NO es reentrega):
        # debe responder de nuevo, no silenciarse.
        res2 = self.Agent.process_message(self.session, 'Hola', wamid='WAMID_2')
        self.assertNotEqual(res2.get('fast_path'), 'dup_wamid')
        self.assertFalse(res2.get('skip_send'))
        self.assertTrue(res2.get('meta_payload'))
