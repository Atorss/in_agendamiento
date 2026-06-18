# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestAiSession(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': 'Test AI Session Co',
            'wa_phone_number_id': 'PHN_AI_SESS',
        })

    def test_create_session_default_state(self):
        session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id,
            'wa_from': '+593999000111',
        })
        self.assertEqual(session.state, 'nueva')
        self.assertFalse(session.partner_id)
        self.assertTrue(session.token)
        self.assertEqual(len(session.token), 32)

    def test_session_state_transition(self):
        session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id,
            'wa_from': '+593999000111',
        })
        session.action_set_state('identificando_cliente')
        self.assertEqual(session.state, 'identificando_cliente')

        session.action_set_state('conversando')
        self.assertEqual(session.state, 'conversando')

    def test_invalid_state_raises(self):
        session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id,
            'wa_from': '+593999000111',
        })
        with self.assertRaises(UserError):
            session.action_set_state('estado_inexistente')

    def test_append_message(self):
        session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id,
            'wa_from': '+593999000111',
        })
        session.append_message(role='user', content='hola')
        session.append_message(role='assistant', content='hola!')
        self.assertEqual(len(session.message_ids), 2)
        # message_ids viene ordenado asc por create_date
        msgs = session.message_ids.sorted('id')
        self.assertEqual(msgs[0].role, 'user')
        self.assertEqual(msgs[1].role, 'assistant')

    def test_get_or_create_returns_same_active_session(self):
        s1 = self.env['innatum.ai.session'].get_or_create(
            company=self.company, wa_from='+593999000111')
        s2 = self.env['innatum.ai.session'].get_or_create(
            company=self.company, wa_from='+593999000111')
        self.assertEqual(s1.id, s2.id)

    def test_get_or_create_new_session_after_terminal_state(self):
        s1 = self.env['innatum.ai.session'].get_or_create(
            company=self.company, wa_from='+593999000111')
        s1.action_set_state('realizada')
        s2 = self.env['innatum.ai.session'].get_or_create(
            company=self.company, wa_from='+593999000111')
        self.assertNotEqual(s1.id, s2.id)
        self.assertEqual(s2.state, 'nueva')
