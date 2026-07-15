# -*- coding: utf-8 -*-
import json
import time

from .common_wa_fase2 import Fase2Case
from ..models.wa_flow_token import get_flow_token_secret, make_flow_token


class FlowDisparoCase(Fase2Case):

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.session = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '593991112223',
            'partner_id': self.paciente.id,
        })
        self.session.action_set_state('menu_principal')

    def _habilitar_flow(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_wa.flows_enabled', 'True')
        self.company.wa_flow_id = '111222333'
        kp = self.env['innatum.wa.flow.keypair'].create(
            {'company_id': self.company.id})
        kp.action_generate()


class TestFlowDisparo(FlowDisparoCase):

    def test_flag_apagado_usa_listas(self):
        res = self.Agent.process_message(
            self.session, 'menu:agendar', wamid='W_FD_1')
        self.assertNotEqual(res.get('fast_path'), 'flow_agendar')

    def test_flag_encendido_envia_flow(self):
        self._habilitar_flow()
        res = self.Agent.process_message(
            self.session, 'menu:agendar', wamid='W_FD_2')
        self.assertEqual(res.get('fast_path'), 'flow_agendar')
        inter = res['meta_payload']['interactive']
        self.assertEqual(inter['type'], 'flow')
        params = inter['action']['parameters']
        self.assertEqual(params['flow_message_version'], '3')
        self.assertEqual(params['flow_id'], '111222333')
        self.assertEqual(params['flow_action'], 'data_exchange')
        from ..models.wa_flow_token import check_flow_token
        sid = check_flow_token(params['flow_token'],
                               get_flow_token_secret(self.env), time.time())
        self.assertEqual(sid, self.session.id)

    def test_sin_flow_id_usa_listas(self):
        self._habilitar_flow()
        self.company.wa_flow_id = False
        res = self.Agent.process_message(
            self.session, 'menu:agendar', wamid='W_FD_3')
        self.assertNotEqual(res.get('fast_path'), 'flow_agendar')


class TestNfmReply(FlowDisparoCase):

    def _nfm(self, payload_dict, wamid):
        return self.Agent.process_message(
            self.session, json.dumps(payload_dict),
            message_type='nfm_reply', wamid=wamid)

    def test_confirmacion_con_turno(self):
        turno = self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': '2099-03-02 15:00:00',
            'state': 'reserved',
        })
        token = make_flow_token(self.session.id,
                                get_flow_token_secret(self.env), time.time())
        res = self._nfm({'flow_token': token, 'turno_id': turno.id},
                        'W_NFM_1')
        self.assertIn('agendada', res['response_text'])
        self.assertIn('Endodoncia', res['response_text'])
        self.assertEqual(self.session.state, 'confirmada')

    def test_token_invalido_respuesta_generica(self):
        res = self._nfm({'flow_token': 'ft1:9:9:x'}, 'W_NFM_2')
        self.assertTrue(res['response_text'])
        self.assertNotIn('agendada', res['response_text'])

    def test_json_corrupto_no_rompe(self):
        res = self.Agent.process_message(
            self.session, '{{{no-json', message_type='nfm_reply',
            wamid='W_NFM_3')
        self.assertTrue(res['response_text'])

    def test_json_valido_no_dict_no_rompe(self):
        res = self.Agent.process_message(
            self.session, '[1,2,3]', message_type='nfm_reply',
            wamid='W_NFM_4')
        self.assertTrue(res['response_text'])
        self.assertNotIn('agendada', res['response_text'])

    def test_turno_id_no_numerico_no_rompe(self):
        import time
        from ..models.wa_flow_token import (get_flow_token_secret,
                                            make_flow_token)
        token = make_flow_token(self.session.id,
                                get_flow_token_secret(self.env), time.time())
        res = self._nfm({'flow_token': token, 'turno_id': 'abc'},
                        'W_NFM_5')
        self.assertTrue(res['response_text'])
        self.assertNotIn('agendada', res['response_text'])

    def test_turno_de_otro_paciente_respuesta_generica(self):
        """F3: token de sesión válido + turno_id del MISMO tenant pero de
        OTRO paciente no debe confirmar (evita enumerar turnos ajenos)."""
        otro_partner = self.env['res.partner'].create({
            'name': 'Otro Paciente', 'company_id': self.company.id,
            'mobile': '0990001111',
        })
        turno = self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': otro_partner.id,
            'date_start': '2099-03-02 15:00:00',
            'state': 'reserved',
        })
        token = make_flow_token(self.session.id,
                                get_flow_token_secret(self.env), time.time())
        res = self._nfm({'flow_token': token, 'turno_id': turno.id},
                        'W_NFM_6')
        self.assertNotIn('agendada', res['response_text'])
        self.assertNotEqual(self.session.state, 'confirmada')
