# -*- coding: utf-8 -*-
from .common_wa_fase2 import Fase2Case


class TestIdentidadStaff(Fase2Case):
    """Normalización del número del empleado y resolución de actor."""

    def test_wa_number_normalized_se_computa(self):
        self.assertEqual(self.colaboradora.wa_number_normalized,
                         '593996706629')

    def test_wa_number_normalized_sin_movil(self):
        emp = self.env['hr.employee'].create({
            'name': 'Sin Cel', 'company_id': self.company.id,
        })
        self.assertFalse(emp.wa_number_normalized)

    def test_wa_number_normalized_se_recalcula(self):
        self.colaboradora.mobile_phone = '0999888777'
        self.assertEqual(self.colaboradora.wa_number_normalized,
                         '593999888777')

    def test_ensure_actor_staff(self):
        session = self._session_de('593996706629')
        self.assertEqual(session.ensure_actor(), 'staff')
        self.assertEqual(session.employee_id, self.colaboradora)
        self.assertEqual(session.actor, 'staff')

    def test_ensure_actor_paciente(self):
        session = self._session_de('593991112223')
        self.assertEqual(session.ensure_actor(), 'paciente')
        self.assertFalse(session.employee_id)

    def test_ensure_actor_empleado_archivado_vuelve_a_paciente(self):
        session = self._session_de('593996706629')
        self.assertEqual(session.ensure_actor(), 'staff')
        self.colaboradora.active = False
        self.assertEqual(session.ensure_actor(), 'paciente')
        self.assertFalse(session.employee_id)


class TestRouterStaff(Fase2Case):
    """process_message desvía a staff; los pacientes siguen igual."""

    def test_staff_es_ruteado_al_agente_staff(self):
        session = self._session_de('593996706629')
        res = self.Agent.process_message(session, 'hola', wamid='W_ST_1')
        self.assertTrue(res.get('fast_path', '').startswith('staff'))

    def test_paciente_no_es_ruteado(self):
        session = self._session_de('593991112223')
        res = self.Agent.process_message(session, 'hola', wamid='W_PA_1')
        self.assertFalse((res.get('fast_path') or '').startswith('staff'))

    def test_staff_menu_sin_derivaciones(self):
        session = self._session_de('593996706629')
        res = self.Agent.process_message(session, 'hola', wamid='W_ST_2')
        self.assertIn('No tienes derivaciones pendientes',
                      res['response_text'])
        self.assertEqual(session.state, 'staff_menu')

    def test_staff_menu_una_derivacion_entra_directo(self):
        deriv = self._crear_derivacion()
        session = self._session_de('593996706629')
        res = self.Agent.process_message(session, 'hola', wamid='W_ST_3')
        self.assertEqual(session.staff_derivacion_id, deriv)
        self.assertTrue(res.get('meta_payload'))

    def test_staff_menu_varias_derivaciones_lista(self):
        d1 = self._crear_derivacion()
        otro_paciente = self.env['res.partner'].create({
            'name': 'María Vera', 'company_id': self.company.id})
        d2 = self.Turno.create({
            'es_derivacion': True, 'state': 'derivado',
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'partner_id': otro_paciente.id,
            'derivado_por_id': self.derivador.id,
        })
        session = self._session_de('593996706629')
        res = self.Agent.process_message(session, 'hola', wamid='W_ST_4')
        payload = res['meta_payload']
        rows = payload['interactive']['action']['sections'][0]['rows']
        self.assertEqual({r['id'] for r in rows},
                         {f'st_deriv:{d1.id}', f'st_deriv:{d2.id}'})
        self.assertEqual(session.state, 'staff_menu')
