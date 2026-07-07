# -*- coding: utf-8 -*-
"""Fixture común de la Fase 2: tenant con suscripción activa, colaboradora
con celular (staff), doctor que deriva, paciente con celular y servicio.
La suscripción es obligatoria: hr.employee._check_plan_max_profesionales
(innatum_agenda_planes) exige una suscripción vigente en la company.
"""
from odoo.tests.common import TransactionCase


class Fase2Case(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': 'Clínica F2',
            'wa_phone_number_id': '222333444555',
        })
        plan = self.env['in_agenda.plan'].create({
            'name': 'Test Plan F2', 'code': 'TEST_F2',
        })
        self.env['in_agenda.suscripcion'].create({
            'company_id': self.company.id,
            'plan_id': plan.id,
            'fecha_fin': '2099-12-31',
            'state': 'active',
        })
        self.colaboradora = self.env['hr.employee'].create({
            'name': 'Dra. Ana',
            'company_id': self.company.id,
            'mobile_phone': '0996706629',   # staff: 593996706629
        })
        self.derivador = self.env['hr.employee'].create({
            'name': 'Dr. Baratau',
            'company_id': self.company.id,
            'mobile_phone': '0987654321',   # 593987654321
        })
        self.paciente = self.env['res.partner'].create({
            'name': 'Juan Pérez',
            'company_id': self.company.id,
            'mobile': '0991112223',         # 593991112223
        })
        self.servicio = self.env['innatum.agenda.servicio'].create({
            'name': 'Endodoncia',
            'company_id': self.company.id,
            'duracion': 60.0,
        })
        self.Turno = self.env['innatum.agenda.turno']
        self.Propuesta = self.env['innatum.agenda.turno.propuesta']
        self.Outbound = self.env['innatum.wa.outbound']
        self.Session = self.env['innatum.ai.session']
        self.Agent = self.env['innatum.whatsapp.agent']

    def _crear_derivacion(self):
        return self.Turno.create({
            'es_derivacion': True,
            'state': 'derivado',
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'partner_id': self.paciente.id,
            'derivado_por_id': self.derivador.id,
        })

    def _session_de(self, wa_from):
        return self.Session.get_or_create(self.company, wa_from)

    def _cola(self, template_name=None):
        dom = []
        if template_name:
            recs = self.Outbound.search([])
            return recs.filtered(
                lambda r: r.meta_payload.get('template', {}).get('name')
                == template_name)
        return self.Outbound.search(dom)
