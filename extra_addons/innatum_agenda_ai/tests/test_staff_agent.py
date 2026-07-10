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

    def _horas_del_primer_dia(self, wamid):
        """Navega días→horas: st_addmore → lista de días → tap primer
        día → respuesta con las horas de ese día."""
        res = self._staff('st_addmore', wamid + '_d')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        dias = [r['id'] for r in rows if r['id'].startswith('st_day:')]
        self.assertTrue(dias, 'La lista debe traer días st_day:*')
        return self._staff(dias[0], wamid + '_h')

    def test_addmore_muestra_dias(self):
        res = self._staff('st_addmore', 'W_TS_D1')
        self.assertEqual(res.get('fast_path'), 'staff_dias')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertTrue(all(r['id'].startswith('st_day:')
                            or r['id'] == 'st_dmore' for r in rows))
        self.assertLessEqual(len(rows), 10)
        dias = [r for r in rows if r['id'].startswith('st_day:')]
        self.assertTrue(all('libre' in r['description'] for r in dias))
        # Jornada L-V: sin sábados ni domingos.
        self.assertFalse([r for r in dias
                          if r['title'].startswith(('sáb', 'dom'))])

    def test_dia_abre_sus_horas(self):
        res = self._horas_del_primer_dia('W_TS_D2')
        self.assertEqual(res.get('fast_path'), 'staff_horas')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertLessEqual(len(rows), 10)
        self.assertEqual(rows[-1]['id'], 'st_days')
        self.assertTrue([r for r in rows if r['id'].startswith('st_slot:')])
        self.assertTrue(self.session.staff_dia)

    def test_otros_dias_regresa_a_la_lista_de_dias(self):
        self._horas_del_primer_dia('W_TS_D3')
        res = self._staff('st_days', 'W_TS_D4')
        self.assertEqual(res.get('fast_path'), 'staff_dias')
        self.assertFalse(self.session.staff_dia)

    def test_mas_horas_solo_con_muchos_huecos(self):
        # 60 min → ~8 huecos/día: sin st_hmore.
        res = self._horas_del_primer_dia('W_TS_D5')
        ids = [r['id'] for r in
               res['meta_payload']['interactive']['action']['sections'][0]['rows']]
        self.assertNotIn('st_hmore', ids)
        # 30 min → ~16 huecos/día: aparece y pagina.
        self.servicio.duracion = 30.0
        self._staff('st_days', 'W_TS_D6')
        res2 = self._horas_del_primer_dia('W_TS_D7')
        rows2 = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertEqual(rows2[-2]['id'], 'st_hmore')
        primera = rows2[0]['id']
        res3 = self._staff('st_hmore', 'W_TS_D8')
        rows3 = res3['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotEqual(rows3[0]['id'], primera)

    def test_tap_boton_plantilla_abre_esa_derivacion(self):
        """El payload st_deriv:<id> del botón de la plantilla abre ESA
        derivación sin importar el contexto previo de la sesión."""
        paciente2 = self.env['res.partner'].create({
            'name': 'María López', 'company_id': self.company.id,
            'mobile': '0994445556'})
        deriv2 = self.Turno.create({
            'es_derivacion': True,
            'state': 'derivado',
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'partner_id': paciente2.id,
            'derivado_por_id': self.derivador.id,
        })
        res = self._staff('st_deriv:%d' % deriv2.id, 'W_TS_COLD')
        self.assertEqual(res.get('fast_path'), 'staff_dias')
        self.assertIn('María López', res['response_text'])
        self.assertEqual(self.session.staff_derivacion_id, deriv2)

    def test_lista_trae_huecos_y_formato(self):
        res = self._horas_del_primer_dia('W_TS_1')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertTrue(all(len(r['title']) <= 24 for r in rows))
        self.assertLessEqual(len(rows), 10)

    def test_tap_crea_propuesta_y_botones(self):
        res = self._horas_del_primer_dia('W_TS_2')
        slot_id = self._primer_slot_id(res)
        res2 = self._staff(slot_id, 'W_TS_3')
        self.assertEqual(len(self.deriv.propuesta_ids), 1)
        botones = res2['meta_payload']['interactive']['action']['buttons']
        ids = [b['reply']['id'] for b in botones]
        self.assertEqual(ids, ['st_addmore', 'st_confirm', 'st_cancel'])

    def test_slot_propuesto_desaparece_de_la_lista(self):
        res = self._horas_del_primer_dia('W_TS_4')
        slot_id = self._primer_slot_id(res)
        self._staff(slot_id, 'W_TS_5')
        res2 = self._horas_del_primer_dia('W_TS_6')
        rows = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotIn(slot_id, [r['id'] for r in rows])

    def test_slot_ocupado_no_aparece(self):
        res = self._horas_del_primer_dia('W_TS_7')
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
        res2 = self._horas_del_primer_dia('W_TS_8')
        rows = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotIn(slot_id, [r['id'] for r in rows])

    def test_fmt_dt_ec(self):
        # 2099-07-15 15:00 UTC = 10:00 Ecuador; 15/07/2099 es miércoles.
        dt = fields.Datetime.to_datetime('2099-07-15 15:00:00')
        self.assertEqual(self.Agent._fmt_dt_ec(dt), 'mié 15 jul · 10:00')

    def test_tap_slot_recien_ocupado_no_persiste_propuesta(self):
        from odoo import fields as odoo_fields
        res = self._horas_del_primer_dia('W_TS_C1')
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
        res = self._horas_del_primer_dia('W_TS_C3')
        slot_id = self._primer_slot_id(res)
        self._staff(slot_id, 'W_TS_C4')
        res2 = self._staff(slot_id, 'W_TS_C5')
        self.assertEqual(len(self.deriv.propuesta_ids), 1)
        self.assertIn('ya está en tus propuestas', res2['response_text'])

    def test_paginacion_mas_dias(self):
        # 21 días L-V ≈ 15 días con huecos → 2 páginas.
        res = self._staff('st_addmore', 'W_TS_P1')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertEqual(rows[-1]['id'], 'st_dmore',
                         'Con >9 días debe aparecer la fila Más días')
        primera_pg1 = rows[0]['id']
        res2 = self._staff('st_dmore', 'W_TS_P2')
        rows2 = res2['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertNotEqual(rows2[0]['id'], primera_pg1,
                            'La página 2 debe traer días distintos')


class TestStaffConfirmar(Fase2Case):

    def setUp(self):
        super().setUp()
        self.deriv = self._crear_derivacion()
        self.session = self._session_de('593996706629')
        self.Agent.process_message(self.session, 'hola', wamid='W_TC_0')
        res = self.Agent.process_message(self.session, 'st_addmore',
                                         wamid='W_TC_1')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        dia = [r['id'] for r in rows if r['id'].startswith('st_day:')][0]
        res = self.Agent.process_message(self.session, dia, wamid='W_TC_1b')
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


class TestStaffFechaEscrita(Fase2Case):
    """El colaborador escribe la fecha en vez de navegar las listas."""

    def setUp(self):
        super().setUp()
        self.deriv = self._crear_derivacion()
        self.session = self._session_de('593996706629')
        self.Agent.process_message(self.session, 'hola', wamid='W_FE_0')

    def _staff(self, text, wamid):
        return self.Agent.process_message(self.session, text, wamid=wamid)

    def _rows(self, res):
        return res['meta_payload']['interactive']['action']['sections'][0]['rows']

    def _primer_slot_utc(self, pref):
        """Primer hueco libre real (datetime UTC), navegando las listas."""
        res = self._staff('st_addmore', pref + '_a')
        dia = [r['id'] for r in self._rows(res)
               if r['id'].startswith('st_day:')][0]
        res2 = self._staff(dia, pref + '_b')
        slot = [r['id'] for r in self._rows(res2)
                if r['id'].startswith('st_slot:')][0]
        # Volver al nivel de días para no dejar día en contexto.
        self._staff('st_days', pref + '_c')
        return fields.Datetime.to_datetime(slot.split('st_slot:')[1])

    def test_fecha_valida_agrega_propuesta(self):
        dt = self._primer_slot_utc('W_FE_1')
        local = dt - timedelta(hours=5)
        texto = '%d/%d %d:%02d' % (local.day, local.month,
                                   local.hour, local.minute)
        res = self._staff(texto, 'W_FE_2')
        self.assertEqual(self.deriv.propuesta_ids.mapped('date_start'), [dt])
        botones = res['meta_payload']['interactive']['action']['buttons']
        self.assertEqual([b['reply']['id'] for b in botones],
                         ['st_addmore', 'st_confirm', 'st_cancel'])

    def test_fuera_de_jornada_relista_horas_del_dia(self):
        dt = self._primer_slot_utc('W_FE_3')
        local = dt - timedelta(hours=5)
        res = self._staff('%d/%d 23:45' % (local.day, local.month),
                          'W_FE_4')
        self.assertIn('no está disponible', res['response_text'])
        self.assertEqual(res.get('fast_path'), 'staff_horas')
        self.assertFalse(self.deriv.propuesta_ids)

    def test_fecha_pasada_avisa(self):
        res = self._staff('01/01/2020 10:00', 'W_FE_5')
        self.assertIn('ya pasó', res['response_text'])
        self.assertEqual(res.get('fast_path'), 'staff_dias')

    def test_fuera_de_ventana_avisa(self):
        lejos = fields.Datetime.now() + timedelta(days=30)
        local = lejos - timedelta(hours=5)
        res = self._staff('%d/%d/%d 10:00' % (local.day, local.month,
                                              local.year), 'W_FE_6')
        self.assertIn('21 días', res['response_text'])
        self.assertEqual(res.get('fast_path'), 'staff_dias')

    def test_no_parseable_da_ayuda_y_dias(self):
        res = self._staff('el lunes que viene tempranito', 'W_FE_7')
        self.assertIn('No logré entender', res['response_text'])
        self.assertEqual(res.get('fast_path'), 'staff_dias')

    def test_hora_sola_usa_dia_en_contexto(self):
        res = self._staff('st_addmore', 'W_FE_8')
        dia = [r['id'] for r in self._rows(res)
               if r['id'].startswith('st_day:')][0]
        res2 = self._staff(dia, 'W_FE_9')
        slot = [r['id'] for r in self._rows(res2)
                if r['id'].startswith('st_slot:')][0]
        dt = fields.Datetime.to_datetime(slot.split('st_slot:')[1])
        local = dt - timedelta(hours=5)
        res3 = self._staff('%d:%02d' % (local.hour, local.minute),
                           'W_FE_10')
        self.assertEqual(self.deriv.propuesta_ids.mapped('date_start'),
                         [dt])
        self.assertIn('Agregado', res3['response_text'])

    def test_hora_sola_sin_contexto_pide_ayuda(self):
        self._staff('st_addmore', 'W_FE_11')   # nivel días: sin staff_dia
        res = self._staff('3pm', 'W_FE_12')
        self.assertIn('No logré entender', res['response_text'])

    def test_fecha_duplicada_no_disponible(self):
        dt = self._primer_slot_utc('W_FE_13')
        local = dt - timedelta(hours=5)
        texto = '%d/%d %d:%02d' % (local.day, local.month,
                                   local.hour, local.minute)
        self._staff(texto, 'W_FE_14')
        res = self._staff(texto, 'W_FE_15')
        self.assertEqual(len(self.deriv.propuesta_ids), 1)
        self.assertIn('no está disponible', res['response_text'])

    def test_texto_sin_fecha_en_horas_resetea_pagina(self):
        # Hallazgo 1: al bajar de nivel (horas -> días) por texto no
        # parseable, staff_slot_page debe resetear a 0 (era compartida
        # con la paginación de horas y quedaba "pegada").
        self.servicio.duracion = 30.0   # ~16 huecos/día: habilita st_hmore
        res = self._staff('st_addmore', 'W_FE_16')
        dia = [r['id'] for r in self._rows(res)
               if r['id'].startswith('st_day:')][0]
        self._staff(dia, 'W_FE_17')       # nivel horas, página 0
        self._staff('st_hmore', 'W_FE_18')  # paginamos horas -> página 1
        self.assertEqual(self.session.staff_slot_page, 1)
        self.assertTrue(self.session.staff_dia)
        res2 = self._staff('texto sin fecha', 'W_FE_19')
        self.assertEqual(res2.get('fast_path'), 'staff_dias')
        self.assertEqual(self.session.staff_slot_page, 0)

    def test_paginacion_dias_no_afectada_por_el_fix(self):
        # El fix del hallazgo 1 no debe tocar la paginación YA estando en
        # el nivel de días (staff_dia vacío): texto no parseable debe
        # conservar la página de días en la que el usuario estaba.
        res = self._staff('st_addmore', 'W_FE_20b')
        self.assertEqual(self._rows(res)[-1]['id'], 'st_dmore')
        self._staff('st_dmore', 'W_FE_21b')
        self.assertEqual(self.session.staff_slot_page, 1)
        res2 = self._staff('texto sin fecha', 'W_FE_22b')
        self.assertEqual(res2.get('fast_path'), 'staff_dias')
        self.assertEqual(self.session.staff_slot_page, 1)

    def test_fecha_escrita_exitosa_fija_staff_dia(self):
        # Hallazgo 2: tras una fecha escrita exitosa, staff_dia debe
        # quedar fijado en ESE día, para que una hora suelta posterior
        # ("8:30") se resuelva sobre el mismo día y no sobre un día
        # previamente tapeado que haya quedado en el contexto.
        dt = self._primer_slot_utc('W_FE_23b')
        local = dt - timedelta(hours=5)
        texto = '%d/%d %d:%02d' % (local.day, local.month,
                                   local.hour, local.minute)
        self._staff(texto, 'W_FE_24b')
        self.assertEqual(self.deriv.propuesta_ids.mapped('date_start'), [dt])
        self.assertEqual(self.session.staff_dia, local.date())
        self.assertEqual(self.session.staff_slot_page, 0)

        # Otro hueco libre del MISMO día (distinto de dt), consultado
        # directamente al agente sin volver a navegar (para no volver a
        # fijar staff_dia por el tap y así probar el fix aislado).
        StaffAgent = self.env['innatum.whatsapp.staff.agent']
        otros = [s for s in StaffAgent._slots_libres(self.deriv)
                 if (s - timedelta(hours=5)).date() == local.date()
                 and s != dt]
        self.assertTrue(otros, 'debe haber otro hueco libre el mismo día')
        otro = otros[0]
        otro_local = otro - timedelta(hours=5)
        self._staff('%d:%02d' % (otro_local.hour, otro_local.minute),
                    'W_FE_25b')
        self.assertEqual(
            sorted(self.deriv.propuesta_ids.mapped('date_start')),
            sorted([dt, otro]))

    def test_menu_limpia_staff_dia(self):
        # Hallazgo 3: _menu debe limpiar staff_dia igual que limpia
        # staff_derivacion_id y staff_slot_page. Se crea una segunda
        # derivación pendiente para que _menu liste (len(pendientes) != 1)
        # en vez de delegar a _abrir_derivacion (que ya limpia staff_dia
        # por su cuenta y ocultaría el bug).
        paciente2 = self.env['res.partner'].create({
            'name': 'Otro Paciente', 'company_id': self.company.id,
            'mobile': '0994445557'})
        self.Turno.create({
            'es_derivacion': True,
            'state': 'derivado',
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'partner_id': paciente2.id,
            'derivado_por_id': self.derivador.id,
        })
        self._staff('st_cancel', 'W_FE_26b')
        self.session.staff_dia = '2099-01-01'
        self._staff('hola de nuevo', 'W_FE_27b')
        self.assertFalse(self.session.staff_dia)
