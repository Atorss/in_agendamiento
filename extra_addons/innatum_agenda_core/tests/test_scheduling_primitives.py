# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestFormatPrice(TransactionCase):
    """El helper _format_price respeta el símbolo y la posición de la moneda
    de la company (usado por list_services para reportar precio_label)."""

    def setUp(self):
        super().setUp()
        self.prim = self.env['innatum.agenda.scheduling.primitives']

    def test_symbol_before(self):
        usd = self.env.ref('base.USD')
        usd.position = 'before'
        company = self.env['res.company'].create({
            'name': 'Co USD', 'currency_id': usd.id,
        })
        self.assertEqual(
            self.prim._format_price(25.0, company),
            '%s25.00' % usd.symbol,
        )

    def test_symbol_after(self):
        eur = self.env.ref('base.EUR')
        eur.position = 'after'
        company = self.env['res.company'].create({
            'name': 'Co EUR', 'currency_id': eur.id,
        })
        self.assertEqual(
            self.prim._format_price(25.0, company),
            '25.00 %s' % eur.symbol,
        )

    def test_two_decimals(self):
        usd = self.env.ref('base.USD')
        company = self.env['res.company'].create({
            'name': 'Co Dec', 'currency_id': usd.id,
        })
        # Siempre 2 decimales aunque el precio sea entero.
        self.assertIn('.00', self.prim._format_price(30, company))
        self.assertIn('19.90', self.prim._format_price(19.9, company))
