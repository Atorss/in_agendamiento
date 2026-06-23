# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestBusinessKnowledge(TransactionCase):
    """search_knowledge: recuperación por palabras clave, sin match, y
    aislamiento por compañía (tool buscar_conocimiento del agente)."""

    def setUp(self):
        super().setUp()
        self.Knowledge = self.env['innatum.business.knowledge']
        self.company = self.env['res.company'].create({'name': 'Clínica A'})
        self.session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id, 'wa_from': '593900000001',
        })
        self.Knowledge.create({
            'company_id': self.company.id,
            'name': '¿Tienen parqueadero?',
            'answer': 'Sí, contamos con parqueadero gratuito atrás del edificio.',
            'keywords': 'estacionamiento, carro, auto',
        })
        self.Knowledge.create({
            'company_id': self.company.id,
            'name': 'Formas de pago',
            'answer': 'Aceptamos efectivo, tarjeta y transferencia.',
            'keywords': 'pago, tarjeta, efectivo',
        })

    def test_finds_by_keyword(self):
        res = self.Knowledge.search_knowledge(
            {'query': '¿dónde dejo el carro?'}, session=self.session)
        self.assertEqual(res.get('total'), 1)
        self.assertIn('parqueadero', res['resultados'][0]['respuesta'].lower())

    def test_finds_by_topic_word(self):
        res = self.Knowledge.search_knowledge(
            {'query': 'puedo pagar con tarjeta'}, session=self.session)
        self.assertTrue(res.get('resultados'))
        self.assertIn('tarjeta', res['resultados'][0]['respuesta'].lower())

    def test_no_match_returns_message(self):
        res = self.Knowledge.search_knowledge(
            {'query': 'horóscopo chino'}, session=self.session)
        self.assertEqual(res['resultados'], [])
        self.assertIn('message', res)

    def test_empty_query_returns_message(self):
        res = self.Knowledge.search_knowledge(
            {'query': ''}, session=self.session)
        self.assertEqual(res['resultados'], [])
        self.assertIn('message', res)

    def test_multi_tenant_isolation(self):
        # Otra compañía sin entradas NO debe ver las de la Clínica A.
        company_b = self.env['res.company'].create({'name': 'Clínica B'})
        session_b = self.env['innatum.ai.session'].create({
            'company_id': company_b.id, 'wa_from': '593900000002',
        })
        res = self.Knowledge.search_knowledge(
            {'query': 'parqueadero'}, session=session_b)
        self.assertEqual(res['resultados'], [])
