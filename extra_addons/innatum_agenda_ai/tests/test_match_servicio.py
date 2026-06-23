# -*- coding: utf-8 -*-
from unittest.mock import patch
from odoo.tests.common import TransactionCase


class TestMatchServicio(TransactionCase):
    """_match_servicio: enruta texto libre al código de servicio igual que el
    botón servicio:CODE. Aísla list_services con un stub para no depender de
    turnos reales."""

    def setUp(self):
        super().setUp()
        self.Agent = self.env['innatum.whatsapp.agent']
        self.company = self.env['res.company'].create({'name': 'Clínica Match'})
        self.session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id, 'wa_from': '593900000777',
        })
        self.Primitives = self.env['innatum.agenda.scheduling.primitives']

    def _match(self, text, especialidades):
        data = {'especialidades': especialidades}
        with patch.object(type(self.Primitives), 'list_services',
                          return_value=data):
            return self.Agent._match_servicio(text, self.session)

    DATA = [
        {'name': 'Ortodoncia', 'code': 'ORT'},
        {'name': 'Cirugia Dental', 'code': 'CIR_DENTAL'},
        {'name': 'Servicio Odontológico', 'code': 'ODON'},
    ]

    def test_exact_name_with_accents_and_case(self):
        self.assertEqual(self._match('ORTODONCÍA', self.DATA), 'ORT')

    def test_name_contained_in_free_text(self):
        self.assertEqual(self._match('quiero ortodoncia por favor', self.DATA),
                         'ORT')

    def test_exact_code(self):
        self.assertEqual(self._match('ort', self.DATA), 'ORT')

    def test_unknown_returns_none(self):
        self.assertIsNone(self._match('horóscopo chino', self.DATA))

    def test_empty_returns_none(self):
        self.assertIsNone(self._match('', self.DATA))

    def test_no_services_returns_none(self):
        self.assertIsNone(self._match('ortodoncia', []))

    def test_multiword_service_contained(self):
        self.assertEqual(self._match('cirugia dental', self.DATA), 'CIR_DENTAL')
