# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestPromptComposerContact(TransactionCase):
    """La sección 'Ubicación y contacto' del system prompt se arma con los
    datos de res.company (dirección, teléfono, email) + el enlace de Maps del
    perfil, omitiendo lo que esté vacío (Opción 1: usar lo que ya tenemos)."""

    def setUp(self):
        super().setUp()
        self.tmpl = self.env['innatum.vertical.template'].create({
            'code': 'odonto_composer',
            'name': 'Odonto Composer',
            'family': 'A',
            'base_personality_prompt': 'Tono clínico amable.',
        })
        self.country = self.env.ref('base.ec')
        self.company = self.env['res.company'].create({
            'name': 'Clínica Sonrisa',
            'street': 'Av. Amazonas N12-34',
            'city': 'Quito',
            'phone': '+593 2 222 3344',
            'email': 'hola@sonrisa.test',
            'country_id': self.country.id,
        })
        self.profile = self.env['innatum.business.profile'].create({
            'company_id': self.company.id,
            'vertical_template_id': self.tmpl.id,
            'business_hours': 'Lun-Vie 9-18',
            'google_maps_url': 'https://maps.google.com/?q=sonrisa',
        })
        self.session = self.env['innatum.ai.session'].create({
            'company_id': self.company.id,
            'wa_from': '593999000111',
        })

    def _compose(self):
        return self.env['innatum.prompt.composer'].compose(self.session)

    def test_contact_section_includes_company_data(self):
        prompt = self._compose()
        self.assertIn('## Ubicación y contacto', prompt)
        self.assertIn('Av. Amazonas N12-34', prompt)
        self.assertIn('Quito', prompt)
        self.assertIn('+593 2 222 3344', prompt)
        self.assertIn('hola@sonrisa.test', prompt)
        self.assertIn('https://maps.google.com/?q=sonrisa', prompt)
        # El horario sigue saliendo del perfil (Contexto del negocio).
        self.assertIn('Lun-Vie 9-18', prompt)

    def test_empty_fields_are_omitted(self):
        # Compañía sin dirección/teléfono/email ni Maps → no se inventa nada.
        company = self.env['res.company'].create({'name': 'Negocio Mínimo'})
        profile = self.env['innatum.business.profile'].create({
            'company_id': company.id,
            'vertical_template_id': self.tmpl.id,
        })
        session = self.env['innatum.ai.session'].create({
            'company_id': company.id,
            'wa_from': '593999000222',
        })
        prompt = self.env['innatum.prompt.composer'].compose(session)
        self.assertNotIn('## Ubicación y contacto', prompt)
        self.assertNotIn('Dirección:', prompt)
