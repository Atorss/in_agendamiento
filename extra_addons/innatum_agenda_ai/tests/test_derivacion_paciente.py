# -*- coding: utf-8 -*-
from .common_wa_fase2 import Fase2Case


class TestPacienteElige(Fase2Case):
    """El paciente elige el horario de su derivación por WhatsApp."""

    def setUp(self):
        super().setUp()
        self.deriv = self._crear_derivacion()
        self.p1 = self.Propuesta.create({
            'derivacion_id': self.deriv.id, 'tipo': 'propuesta',
            'date_start': '2099-03-02 15:00:00',
        })
        self.p2 = self.Propuesta.create({
            'derivacion_id': self.deriv.id, 'tipo': 'propuesta',
            'date_start': '2099-03-03 16:00:00',
        })
        self.deriv.action_confirmar_derivacion()   # state -> propuesto
        # Sesión del paciente ya identificado (evita el flujo de cédula).
        self.session = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '593991112223',
            'partner_id': self.paciente.id,
        })
        self.session.action_set_state('menu_principal')

    def test_oferta_aparece_en_menu(self):
        res = self.Agent._show_main_menu(self.session, self.paciente)
        self.assertEqual(res.get('fast_path'), 'dp_propuestas')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertEqual({r['id'] for r in rows},
                         {f'dp_prop:{self.p1.id}', f'dp_prop:{self.p2.id}'})

    def test_menu_normal_sin_derivaciones(self):
        self.deriv.state = 'cancelled'
        res = self.Agent._show_main_menu(self.session, self.paciente)
        self.assertEqual(res.get('fast_path'), 'menu_main')

    def test_elegir_reserva_el_turno(self):
        res = self.Agent.process_message(
            self.session, f'dp_prop:{self.p1.id}', wamid='W_DP_1')
        botones = res['meta_payload']['interactive']['action']['buttons']
        self.assertEqual(botones[0]['reply']['id'],
                         f'dp_confirm:{self.p1.id}')
        res2 = self.Agent.process_message(
            self.session, f'dp_confirm:{self.p1.id}', wamid='W_DP_2')
        self.assertEqual(self.deriv.state, 'reserved')
        self.assertEqual(str(self.deriv.date_start),
                         '2099-03-02 15:00:00')
        self.assertIn('agendada', res2['response_text'])

    def test_slot_robado_relista_las_restantes(self):
        # Otro turno ocupa el horario de p1 antes de que el paciente confirme.
        self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': '2099-03-02 15:00:00',
            'state': 'reserved',
        })
        res = self.Agent.process_message(
            self.session, f'dp_confirm:{self.p1.id}', wamid='W_DP_3')
        self.assertEqual(self.deriv.state, 'propuesto')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertEqual([r['id'] for r in rows], [f'dp_prop:{self.p2.id}'])

    def test_slot_robado_sin_restantes_reabre_y_avisa_a_staff(self):
        self.p2.unlink()
        self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': '2099-03-02 15:00:00',
            'state': 'reserved',
        })
        res = self.Agent.process_message(
            self.session, f'dp_confirm:{self.p1.id}', wamid='W_DP_4')
        self.assertEqual(self.deriv.state, 'derivado')
        self.assertFalse(self.deriv.propuesta_ids)
        avisos = self._cola('aviso_agenda')
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos.to_number, '593996706629')

    def test_match_por_telefono_sin_partner_en_sesion(self):
        session = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '593991112223',
        })
        derivs = self.Agent._derivaciones_para_elegir(session, False)
        self.assertEqual(derivs, self.deriv)

    def test_paciente_con_dos_derivaciones_ve_lista(self):
        servicio2 = self.env['innatum.agenda.servicio'].create({
            'name': 'Ortodoncia', 'company_id': self.company.id,
            'duracion': 30.0,
        })
        deriv2 = self.Turno.create({
            'es_derivacion': True, 'state': 'derivado',
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': servicio2.id,
            'partner_id': self.paciente.id,
            'derivado_por_id': self.derivador.id,
        })
        self.Propuesta.create({
            'derivacion_id': deriv2.id, 'tipo': 'propuesta',
            'date_start': '2099-04-05 15:00:00',
        })
        deriv2.action_confirmar_derivacion()
        res = self.Agent._show_main_menu(self.session, self.paciente)
        self.assertEqual(res.get('fast_path'), 'dp_offer')
        rows = res['meta_payload']['interactive']['action']['sections'][0]['rows']
        self.assertEqual(
            {r['id'] for r in rows},
            {f'dp_deriv:{self.deriv.id}', f'dp_deriv:{deriv2.id}'})

    def test_show_propuestas_sin_horarios_no_rompe(self):
        (self.p1 + self.p2).unlink()
        res = self.Agent._dp_show_propuestas(self.session, self.deriv)
        self.assertFalse(res.get('meta_payload'))
        self.assertIn('no tiene horarios', res['response_text'])

    def test_tercero_no_puede_confirmar_derivacion_ajena(self):
        intruso = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '593988887777',   # número que no es de nadie
        })
        res = self.Agent.process_message(
            intruso, f'dp_confirm:{self.p1.id}', wamid='W_DP_X1')
        self.assertEqual(self.deriv.state, 'propuesto')  # intacta
        self.assertNotIn('agendada', res['response_text'])
        res2 = self.Agent.process_message(
            intruso, f'dp_prop:{self.p1.id}', wamid='W_DP_X2')
        self.assertNotIn('Confirmamos', res2['response_text'])


class TestConfirmacionesElegir(Fase2Case):

    def setUp(self):
        super().setUp()
        self.deriv = self._crear_derivacion()
        self.prop = self.Propuesta.create({
            'derivacion_id': self.deriv.id, 'tipo': 'propuesta',
            'date_start': '2099-03-02 15:00:00',
        })
        self.deriv.action_confirmar_derivacion()

    def test_elegir_avisa_a_colaborador_y_derivador(self):
        self.prop.action_elegir()
        avisos = self._cola('aviso_agenda')
        self.assertEqual(len(avisos), 2)
        self.assertEqual(
            set(avisos.mapped('to_number')),
            {'593996706629', '593987654321'})
        params = avisos[0].meta_payload['template']['components'][0]['parameters']
        self.assertIn('Juan Pérez', params[1]['text'])
        self.assertIn('se agendó tu derivación', params[1]['text'])

    def test_derivador_sin_numero_degrada_con_chatter(self):
        self.derivador.mobile_phone = False
        self.prop.action_elegir()
        avisos = self._cola('aviso_agenda')
        self.assertEqual(len(avisos), 1)   # solo la colaboradora
        cuerpos = [m or '' for m in self.deriv.message_ids.mapped('body')]
        self.assertTrue(any('Dr. Baratau' in c and 'WhatsApp' in c
                            for c in cuerpos))
