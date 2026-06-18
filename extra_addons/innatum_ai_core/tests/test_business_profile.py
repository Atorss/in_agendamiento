# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from psycopg2 import IntegrityError
from odoo.tools import mute_logger


class TestBusinessProfile(TransactionCase):

    def setUp(self):
        super().setUp()
        self.tmpl = self.env['innatum.vertical.template'].create({
            'code': 'odontologia_bp',
            'name': 'Odontología BP',
            'family': 'A',
            'base_personality_prompt': 'Tono clínico amable.',
        })
        self.company = self.env['res.company'].create({
            'name': 'Odontología Sonrisa Test',
        })

    def test_create_profile(self):
        profile = self.env['innatum.business.profile'].create({
            'company_id': self.company.id,
            'vertical_template_id': self.tmpl.id,
            'personality_prompt': 'Hablamos con tuteo y emojis dentales.',
            'payment_policy': 'sin_cobro',
        })
        self.assertEqual(profile.family, 'A')
        self.assertEqual(profile.payment_policy, 'sin_cobro')
        self.assertTrue(profile.active)

    def test_one_profile_per_company(self):
        self.env['innatum.business.profile'].create({
            'company_id': self.company.id,
            'vertical_template_id': self.tmpl.id,
            'personality_prompt': 'tono A',
        })
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.cr.savepoint():
            self.env['innatum.business.profile'].create({
                'company_id': self.company.id,
                'vertical_template_id': self.tmpl.id,
                'personality_prompt': 'tono B',
            })
            self.env.cr.flush()

    def test_anticipo_requires_valid_percent(self):
        with self.assertRaises(ValidationError):
            self.env['innatum.business.profile'].create({
                'company_id': self.company.id,
                'vertical_template_id': self.tmpl.id,
                'payment_policy': 'anticipo',
                'anticipo_percent': 0,
            })

    def test_anticipo_percent_out_of_range(self):
        with self.assertRaises(ValidationError):
            self.env['innatum.business.profile'].create({
                'company_id': self.company.id,
                'vertical_template_id': self.tmpl.id,
                'payment_policy': 'anticipo',
                'anticipo_percent': 150,
            })


class TestResCompanyExtension(TransactionCase):

    def test_company_has_whatsapp_fields(self):
        company = self.env['res.company'].create({
            'name': 'Test Co',
            'wa_phone_number_id': 'PHN_TEST_111',
            'wa_business_account_id': 'WABA_1',
            'supabase_tenant_id': 'tenant-uuid-here',
        })
        self.assertEqual(company.wa_phone_number_id, 'PHN_TEST_111')
        self.assertEqual(company.wa_business_account_id, 'WABA_1')
        self.assertEqual(company.supabase_tenant_id, 'tenant-uuid-here')

    def test_company_phone_number_id_unique(self):
        self.env['res.company'].create({
            'name': 'Co A', 'wa_phone_number_id': 'PHN_DUPE'})
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.cr.savepoint():
            self.env['res.company'].create({
                'name': 'Co B', 'wa_phone_number_id': 'PHN_DUPE'})
            self.env.cr.flush()
