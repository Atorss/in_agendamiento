# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from psycopg2 import IntegrityError
from odoo.tools import mute_logger


class TestVerticalTemplate(TransactionCase):

    def test_create_minimal(self):
        tmpl = self.env['innatum.vertical.template'].create({
            'code': 'odontologia_t',
            'name': 'Odontología Test',
            'family': 'A',
        })
        self.assertEqual(tmpl.code, 'odontologia_t')
        self.assertEqual(tmpl.family, 'A')
        self.assertTrue(tmpl.active)

    def test_code_unique(self):
        self.env['innatum.vertical.template'].create({
            'code': 'spa_t',
            'name': 'Spa Test',
            'family': 'A',
        })
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.cr.savepoint():
            self.env['innatum.vertical.template'].create({
                'code': 'spa_t',
                'name': 'Spa Test Duplicado',
                'family': 'A',
            })
            self.env.cr.flush()

    def test_family_must_be_A_B_or_HYBRID(self):
        # Odoo Selection ya rechaza valores fuera de la lista (ValueError a
        # nivel ORM, antes del constrains). El assertRaises de Odoo no acepta
        # la forma de tupla, así que verificamos la clase concreta.
        with self.assertRaises(ValueError), self.cr.savepoint():
            self.env['innatum.vertical.template'].create({
                'code': 'xx_t',
                'name': 'Invalida',
                'family': 'Z',
            })
