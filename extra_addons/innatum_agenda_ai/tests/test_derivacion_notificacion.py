# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestNotificacionDerivacion(TransactionCase):
    """Al crear una derivación se encola el WhatsApp al colaborador."""

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': 'Clínica Deriv',
            'wa_phone_number_id': '111222333444',
        })
        # Suscripción SaaS activa: hr.employee._check_plan_max_profesionales
        # (innatum_agenda_planes) exige que la company tenga una suscripción
        # vigente antes de aceptar nuevos empleados.
        plan = self.env['in_agenda.plan'].create({
            'name': 'Test Plan Deriv', 'code': 'TEST_DERIV',
        })
        self.env['in_agenda.suscripcion'].create({
            'company_id': self.company.id,
            'plan_id': plan.id,
            'fecha_fin': '2099-12-31',
            'state': 'active',
        })
        self.colaborador = self.env['hr.employee'].create({
            'name': 'Dra. Ana',
            'company_id': self.company.id,
            'mobile_phone': '0996706629',
        })
        self.derivador = self.env['hr.employee'].create({
            'name': 'Dr. Baratau',
            'company_id': self.company.id,
        })
        self.partner = self.env['res.partner'].create({
            'name': 'Juan Pérez',
            'company_id': self.company.id,
        })
        self.servicio = self.env['innatum.agenda.servicio'].create({
            'name': 'Endodoncia',
            'company_id': self.company.id,
        })
        self.Turno = self.env['innatum.agenda.turno']
        self.Outbound = self.env['innatum.wa.outbound']

    def _crear_derivacion(self):
        return self.Turno.create({
            'es_derivacion': True,
            'state': 'derivado',
            'company_id': self.company.id,
            'professional_id': self.colaborador.id,
            'servicio_id': self.servicio.id,
            'partner_id': self.partner.id,
            'derivado_por_id': self.derivador.id,
        })

    def _cola_de(self, turno):
        return self.Outbound.search([
            ('res_model', '=', 'innatum.agenda.turno'),
            ('res_id', '=', turno.id),
        ])

    def test_derivacion_encola_notificacion(self):
        deriv = self._crear_derivacion()
        cola = self._cola_de(deriv)
        self.assertEqual(len(cola), 1)
        self.assertEqual(cola.category, 'derivacion_colaborador')
        self.assertEqual(cola.to_number, '593996706629')
        self.assertEqual(cola.company_id, self.company)
        tmpl = cola.meta_payload['template']
        self.assertEqual(tmpl['name'], 'derivacion_colaborador')
        params = tmpl['components'][0]['parameters']
        self.assertEqual(
            [p['text'] for p in params],
            ['Dra. Ana', 'Dr. Baratau', 'Juan Pérez', 'Endodoncia'])

    def test_turno_normal_no_encola(self):
        turno = self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaborador.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
        })
        self.assertFalse(self._cola_de(turno))

    def test_sin_movil_degrada_sin_romper(self):
        self.colaborador.mobile_phone = False
        deriv = self._crear_derivacion()
        self.assertTrue(deriv.exists())          # la derivación se creó igual
        self.assertFalse(self._cola_de(deriv))   # no hay mensaje encolado
        cuerpos = [m or '' for m in deriv.message_ids.mapped('body')]
        self.assertTrue(
            any('WhatsApp' in c for c in cuerpos),
            'Debe quedar nota en el chatter de la derivación')
