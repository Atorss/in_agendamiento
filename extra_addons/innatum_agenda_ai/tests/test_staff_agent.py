# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from .common_wa_fase2 import Fase2Case


class TestStaffPropuestas(Fase2Case):
    """El colaborador propone horarios desde WhatsApp."""

    def setUp(self):
        super().setUp()
        # Jornada de trabajo: calendario laboral estándar del empleado
        # (hr.employee crea resource_calendar por defecto: L-V 8-12/13-17).
        self.deriv = self._crear_derivacion()
        self.session = self._session_de('593996706629')
        # Entrar al contexto de la derivación (única → directo).
        self.Agent.process_message(self.session, 'hola', wamid='W_TS_0')

    def _staff(self, text, wamid):
        return self.Agent.process_message(self.session, text, wamid=wamid)

    def _primer_slot_id(self, res):
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        slots = [r for r in rows if r['id'].startswith('st_slot:')]
        self.assertTrue(slots, 'La lista debe traer huecos st_slot:*')
        return slots[0]['id']

    def test_lista_trae_huecos_y_formato(self):
        res = self._staff('st_addmore', 'W_TS_1')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertTrue(all(len(r['title']) <= 24 for r in rows))
        self.assertLessEqual(len(rows), 10)

    def test_tap_crea_propuesta_y_botones(self):
        res = self._staff('st_addmore', 'W_TS_2')
        slot_id = self._primer_slot_id(res)
        res2 = self._staff(slot_id, 'W_TS_3')
        self.assertEqual(len(self.deriv.propuesta_ids), 1)
        botones = res2['meta_payload']['interactive']['action']['buttons']
        ids = [b['reply']['id'] for b in botones]
        self.assertEqual(ids, ['st_addmore', 'st_confirm', 'st_cancel'])

    def test_slot_propuesto_desaparece_de_la_lista(self):
        res = self._staff('st_addmore', 'W_TS_4')
        slot_id = self._primer_slot_id(res)
        self._staff(slot_id, 'W_TS_5')
        res2 = self._staff('st_addmore', 'W_TS_6')
        rows = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotIn(slot_id, [r['id'] for r in rows])

    def test_slot_ocupado_no_aparece(self):
        res = self._staff('st_addmore', 'W_TS_7')
        slot_id = self._primer_slot_id(res)
        dt = fields.Datetime.to_datetime(slot_id.split('st_slot:')[1])
        # Otro turno ocupa exactamente ese hueco.
        self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': dt,
            'state': 'reserved',
        })
        res2 = self._staff('st_addmore', 'W_TS_8')
        rows = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotIn(slot_id, [r['id'] for r in rows])

    def test_fmt_dt_ec(self):
        # 2099-07-15 15:00 UTC = 10:00 Ecuador; 15/07/2099 es miércoles.
        dt = fields.Datetime.to_datetime('2099-07-15 15:00:00')
        self.assertEqual(self.Agent._fmt_dt_ec(dt), 'mié 15 jul · 10:00')

    def test_tap_slot_recien_ocupado_no_persiste_propuesta(self):
        from odoo import fields as odoo_fields
        res = self._staff('st_addmore', 'W_TS_C1')
        slot_id = self._primer_slot_id(res)
        dt = odoo_fields.Datetime.to_datetime(slot_id.split('st_slot:')[1])
        # El hueco se ocupa entre el render y el tap.
        self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': dt,
            'state': 'reserved',
        })
        res2 = self._staff(slot_id, 'W_TS_C2')
        self.assertFalse(self.deriv.propuesta_ids,
                         'La propuesta inválida no debe persistir')
        self.assertIn('ya no está libre', res2['response_text'])

    def test_doble_tap_no_duplica_propuesta(self):
        res = self._staff('st_addmore', 'W_TS_C3')
        slot_id = self._primer_slot_id(res)
        self._staff(slot_id, 'W_TS_C4')
        res2 = self._staff(slot_id, 'W_TS_C5')
        self.assertEqual(len(self.deriv.propuesta_ids), 1)
        self.assertIn('ya está en tus propuestas', res2['response_text'])

    def test_paginacion_ver_mas(self):
        res = self._staff('st_addmore', 'W_TS_P1')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertEqual(rows[-1]['id'], 'st_more',
                         'Con >9 huecos debe aparecer la fila Ver más')
        primera_pg1 = rows[0]['id']
        res2 = self._staff('st_more', 'W_TS_P2')
        rows2 = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotEqual(rows2[0]['id'], primera_pg1,
                            'La página 2 debe traer huecos distintos')


class TestStaffConfirmar(Fase2Case):

    def setUp(self):
        super().setUp()
        self.deriv = self._crear_derivacion()
        self.session = self._session_de('593996706629')
        self.Agent.process_message(self.session, 'hola', wamid='W_TC_0')
        res = self.Agent.process_message(self.session, 'st_addmore',
                                         wamid='W_TC_1')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.slot_id = [r['id'] for r in rows
                        if r['id'].startswith('st_slot:')][0]

    def test_confirmar_pasa_a_propuesto_y_avisa_al_paciente(self):
        self.Agent.process_message(self.session, self.slot_id, wamid='W_TC_2')
        res = self.Agent.process_message(self.session, 'st_confirm',
                                         wamid='W_TC_3')
        self.assertEqual(self.deriv.state, 'propuesto')
        self.assertIn('Listo', res['response_text'])
        cola = self._cola('derivacion_paciente')
        self.assertEqual(len(cola), 1)
        self.assertEqual(cola.to_number, '593991112223')
        params = cola.meta_payload['template']['components'][0]['parameters']
        self.assertEqual(
            [p['text'] for p in params],
            ['Juan Pérez', 'Dr. Baratau', 'Dra. Ana', 'Endodoncia'])
        self.assertEqual(self.session.state, 'staff_menu')
        self.assertFalse(self.session.staff_derivacion_id)

    def test_confirmar_sin_propuestas_avisa(self):
        res = self.Agent.process_message(self.session, 'st_confirm',
                                         wamid='W_TC_4')
        self.assertEqual(self.deriv.state, 'derivado')
        self.assertIn('Aún no has propuesto', res['response_text'])

    def test_cancelar_limpia_propuestas(self):
        self.Agent.process_message(self.session, self.slot_id, wamid='W_TC_5')
        self.assertEqual(len(self.deriv.propuesta_ids), 1)
        self.Agent.process_message(self.session, 'st_cancel', wamid='W_TC_6')
        self.assertFalse(self.deriv.propuesta_ids)
        self.assertEqual(self.deriv.state, 'derivado')

    def test_confirmar_desde_backend_tambien_avisa_al_paciente(self):
        self.Propuesta.create({
            'derivacion_id': self.deriv.id, 'tipo': 'propuesta',
            'date_start': '2099-03-02 15:00:00',
        })
        self.deriv.action_confirmar_derivacion()
        self.assertEqual(len(self._cola('derivacion_paciente')), 1)

    def test_paciente_sin_numero_degrada_con_chatter(self):
        self.paciente.mobile = False
        self.Propuesta.create({
            'derivacion_id': self.deriv.id, 'tipo': 'propuesta',
            'date_start': '2099-03-02 15:00:00',
        })
        self.deriv.action_confirmar_derivacion()
        self.assertFalse(self._cola('derivacion_paciente'))
        cuerpos = [m or '' for m in self.deriv.message_ids.mapped('body')]
        self.assertTrue(any('paciente por WhatsApp' in c for c in cuerpos))
