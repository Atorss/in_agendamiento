# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from .common_wa_fase2 import Fase2Case


class FlowAgentCase(Fase2Case):
    """Fixture: tenant directa con 1 servicio publicado y operadora con
    jornada (la de Fase2Case). El agente de pantallas se prueba EN CLARO
    (el cifrado/transporte es del Task 4)."""

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.session = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '593991112223',
        })
        self.FlowAgent = self.env['innatum.wa.flow.agent']

    def h(self, action, screen=None, data=None):
        return self.FlowAgent.handle(
            self.session, action, screen, data or {}, 'FT-TEST')

    def _pantalla_fecha(self):
        """INIT devuelve SERVICIO (pantalla de entrada); elige el primer
        servicio para llegar a FECHA."""
        res = self.h('INIT')
        if res['screen'] == 'SERVICIO':
            code = res['data']['servicios'][0]['id']
            res = self.h('data_exchange', 'SERVICIO',
                         {'servicio_code': code})
        return res

    def _fecha_disponible(self, res_fecha):
        """Primer día hábil NO listado en unavailable_dates."""
        from datetime import date, datetime
        d = datetime.strptime(res_fecha['data']['min_date'], '%Y-%m-%d').date()
        max_d = datetime.strptime(res_fecha['data']['max_date'], '%Y-%m-%d').date()
        unavailable = set(res_fecha['data']['unavailable_dates'])
        while d <= max_d:
            if d.strftime('%Y-%m-%d') not in unavailable:
                return d.strftime('%Y-%m-%d')
            d += timedelta(days=1)
        self.fail('No hay días disponibles en la ventana')


class TestFlowInit(FlowAgentCase):

    def test_ping(self):
        self.assertEqual(self.h('ping'), {'data': {'status': 'active'}})

    def test_init_un_servicio_muestra_entrada_servicio(self):
        # INIT SIEMPRE devuelve la entrada SERVICIO (aunque haya 1 servicio):
        # requisito del Flow publicado. Antes saltaba a FECHA y lo rompía.
        res = self.h('INIT')
        self.assertEqual(res['screen'], 'SERVICIO')
        codes = {s['id'] for s in res['data']['servicios']}
        self.assertIn(self.servicio.code, codes)

    def test_servicio_unico_avanza_a_fecha(self):
        res = self.h('data_exchange', 'SERVICIO',
                     {'servicio_code': self.servicio.code})
        self.assertEqual(res['screen'], 'FECHA')
        self.assertEqual(res['data']['servicio_code'], self.servicio.code)
        self.assertTrue(res['data']['min_date'])
        self.assertTrue(res['data']['unavailable_dates'])

    def test_init_varios_servicios_muestra_dropdown(self):
        s2 = self.env['innatum.agenda.servicio'].create({
            'name': 'Ortodoncia', 'company_id': self.company.id,
            'duracion': 30.0, 'publicar_web': True,
            'operador_ids': [(6, 0, self.colaboradora.ids)]})
        res = self.h('INIT')
        self.assertEqual(res['screen'], 'SERVICIO')
        codes = {s['id'] for s in res['data']['servicios']}
        self.assertIn(self.servicio.code, codes)
        self.assertIn(s2.code, codes)


class TestFlowFechaHora(FlowAgentCase):

    def test_fecha_devuelve_horas_del_dia(self):
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        res = self.h('data_exchange', 'FECHA',
                     {'servicio_code': self.servicio.code, 'fecha': fecha})
        self.assertEqual(res['screen'], 'HORA')
        self.assertTrue(res['data']['horas'])
        slot = res['data']['horas'][0]
        prof_id, dt_iso = slot['id'].split('|')
        self.assertEqual(int(prof_id), self.colaboradora.id)
        self.assertIn(':', slot['title'])

    def test_hora_sin_partner_pide_identidad(self):
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        horas = self.h('data_exchange', 'FECHA',
                       {'servicio_code': self.servicio.code, 'fecha': fecha})
        slot_id = horas['data']['horas'][0]['id']
        res = self.h('data_exchange', 'HORA',
                     {'servicio_code': self.servicio.code, 'slot_id': slot_id})
        self.assertEqual(res['screen'], 'IDENTIDAD')

    def test_hora_con_partner_va_a_confirmar(self):
        self.session.partner_id = self.paciente.id
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        horas = self.h('data_exchange', 'FECHA',
                       {'servicio_code': self.servicio.code, 'fecha': fecha})
        slot_id = horas['data']['horas'][0]['id']
        res = self.h('data_exchange', 'HORA',
                     {'servicio_code': self.servicio.code, 'slot_id': slot_id})
        self.assertEqual(res['screen'], 'CONFIRMAR')
        self.assertIn('Endodoncia', res['data']['resumen'])


class TestFlowIdentidad(FlowAgentCase):

    CEDULA_OK = '1710034065'  # cédula EC válida (módulo 10)

    def _hasta_identidad(self):
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        horas = self.h('data_exchange', 'FECHA',
                       {'servicio_code': self.servicio.code, 'fecha': fecha})
        self.slot_id = horas['data']['horas'][0]['id']
        return self.h('data_exchange', 'HORA',
                      {'servicio_code': self.servicio.code,
                       'slot_id': self.slot_id})

    def test_identidad_crea_partner_y_confirma(self):
        self._hasta_identidad()
        res = self.h('data_exchange', 'IDENTIDAD', {
            'servicio_code': self.servicio.code, 'slot_id': self.slot_id,
            'cedula': self.CEDULA_OK, 'nombre': 'Pedro Nuevo'})
        self.assertEqual(res['screen'], 'CONFIRMAR')
        p = self.session.partner_id
        self.assertEqual(p.name, 'Pedro Nuevo')
        self.assertEqual(p.vat, self.CEDULA_OK)
        self.assertEqual(p.mobile, '593991112223')

    def test_identidad_cedula_existente_vincula(self):
        self.paciente.vat = self.CEDULA_OK
        self._hasta_identidad()
        self.h('data_exchange', 'IDENTIDAD', {
            'servicio_code': self.servicio.code, 'slot_id': self.slot_id,
            'cedula': self.CEDULA_OK, 'nombre': 'Ignorado'})
        self.assertEqual(self.session.partner_id, self.paciente)

    def test_identidad_cedula_invalida_reintenta(self):
        self._hasta_identidad()
        res = self.h('data_exchange', 'IDENTIDAD', {
            'servicio_code': self.servicio.code, 'slot_id': self.slot_id,
            'cedula': '1234567890', 'nombre': 'X Y'})
        self.assertEqual(res['screen'], 'IDENTIDAD')
        self.assertTrue(res['data']['error_message'])
        self.assertFalse(self.session.partner_id)


class TestFlowReserva(FlowAgentCase):

    def setUp(self):
        super().setUp()
        self.session.partner_id = self.paciente.id

    def _hasta_confirmar(self):
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        horas = self.h('data_exchange', 'FECHA',
                       {'servicio_code': self.servicio.code, 'fecha': fecha})
        self.slot_id = horas['data']['horas'][0]['id']
        self.h('data_exchange', 'HORA',
               {'servicio_code': self.servicio.code, 'slot_id': self.slot_id})

    def test_reserva_crea_turno_y_success(self):
        self._hasta_confirmar()
        res = self.h('data_exchange', 'CONFIRMAR',
                     {'servicio_code': self.servicio.code,
                      'slot_id': self.slot_id})
        self.assertEqual(res['screen'], 'SUCCESS')
        params = res['data']['extension_message_response']['params']
        self.assertEqual(params['flow_token'], 'FT-TEST')
        turno = self.Turno.browse(params['turno_id'])
        self.assertEqual(turno.state, 'reserved')
        self.assertEqual(turno.partner_id, self.paciente)
        prof_id, dt_iso = self.slot_id.split('|')
        self.assertEqual(str(turno.date_start),
                         dt_iso.replace('T', ' '))

    def test_hueco_robado_refresca_confirmar_con_error(self):
        # Meta solo admite rutas hacia adelante: el hueco robado NO navega de
        # vuelta a HORA; refresca CONFIRMAR con aviso para tocar *Atrás*.
        self._hasta_confirmar()
        prof_id, dt_iso = self.slot_id.split('|')
        self.Turno.create({
            'company_id': self.company.id,
            'professional_id': int(prof_id),
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': dt_iso.replace('T', ' '),
            'state': 'reserved',
        })
        before = self.Turno.search_count([])
        res = self.h('data_exchange', 'CONFIRMAR',
                     {'servicio_code': self.servicio.code,
                      'slot_id': self.slot_id})
        self.assertEqual(res['screen'], 'CONFIRMAR')
        self.assertTrue(res['data']['error_message'])
        # No se creó un turno duplicado.
        self.assertEqual(self.Turno.search_count([]), before)


class TestFlowOperadorTenant(FlowAgentCase):
    """F1: el slot_id viaja por el dispositivo del cliente y puede ser
    manipulado. El empleado que resuelve debe pertenecer al tenant de la
    sesión Y ser operador del servicio; si no, no se filtra su nombre ni
    se permite reservar con él (aunque `reserve_directo` ya valida
    company_id, NO valida que el profesional sea operador de ESE
    servicio dentro del mismo tenant)."""

    def setUp(self):
        super().setUp()
        self.session.partner_id = self.paciente.id
        self.company2 = self.env['res.company'].create({
            'name': 'Clínica Ajena', 'wa_phone_number_id': '999888777666',
        })
        plan2 = self.env['in_agenda.plan'].create({
            'name': 'Test Plan Ajeno', 'code': 'TEST_AJENO',
        })
        self.env['in_agenda.suscripcion'].create({
            'company_id': self.company2.id, 'plan_id': plan2.id,
            'fecha_fin': '2099-12-31', 'state': 'active',
        })
        self.empleado_ajeno = self.env['hr.employee'].create({
            'name': 'Dr. Ajeno', 'company_id': self.company2.id,
        })
        self.empleado_no_operador = self.env['hr.employee'].create({
            'name': 'Dr. Sin Servicio', 'company_id': self.company.id,
        })

    def _slot_con_prof(self, prof_id):
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        horas = self.h('data_exchange', 'FECHA',
                       {'servicio_code': self.servicio.code, 'fecha': fecha})
        _, dt_iso = horas['data']['horas'][0]['id'].split('|')
        return '%d|%s' % (prof_id, dt_iso)

    def test_resumen_no_filtra_nombre_de_otro_tenant(self):
        slot_id = self._slot_con_prof(self.empleado_ajeno.id)
        res = self.h('data_exchange', 'HORA',
                     {'servicio_code': self.servicio.code,
                      'slot_id': slot_id})
        self.assertEqual(res['screen'], 'CONFIRMAR')
        self.assertNotIn('Ajeno', res['data']['resumen'])

    def test_reservar_con_prof_no_operador_no_crea_turno(self):
        slot_id = self._slot_con_prof(self.empleado_no_operador.id)
        before = self.Turno.search_count([])
        res = self.h('data_exchange', 'CONFIRMAR',
                     {'servicio_code': self.servicio.code,
                      'slot_id': slot_id})
        self.assertEqual(res['screen'], 'CONFIRMAR')
        self.assertTrue(res['data']['error_message'])
        self.assertEqual(self.Turno.search_count([]), before)


class TestFlowEcoRoto(FlowAgentCase):
    """Eco roto a mitad de flujo NUNCA reinicia a SERVICIO (la pantalla de
    entrada no admite aristas entrantes en el routing_model de Meta): se
    cierra con ERROR_SESION."""

    def test_fecha_con_servicio_invalido_va_a_error_no_a_servicio(self):
        res = self.h('data_exchange', 'FECHA',
                     {'servicio_code': 'no-existe', 'fecha': '2026-08-01'})
        self.assertEqual(res['screen'], 'ERROR_SESION')

    def test_servicio_con_code_invalido_va_a_error_no_a_servicio(self):
        res = self.h('data_exchange', 'SERVICIO',
                     {'servicio_code': 'no-existe'})
        self.assertEqual(res['screen'], 'ERROR_SESION')

    def test_confirmar_con_slot_malformado_va_a_error(self):
        self.session.partner_id = self.paciente.id
        res = self.h('data_exchange', 'CONFIRMAR',
                     {'servicio_code': self.servicio.code,
                      'slot_id': 'basura-sin-pipe'})
        self.assertEqual(res['screen'], 'ERROR_SESION')


class TestFlowBack(FlowAgentCase):
    """F2: BACK debe re-renderizar la pantalla a la que se vuelve (por
    `screen`), no siempre reiniciar el funnel con `_init`."""

    def test_back_screen_hora_devuelve_horas_frescas(self):
        init = self._pantalla_fecha()
        fecha = self._fecha_disponible(init)
        self.h('data_exchange', 'FECHA',
              {'servicio_code': self.servicio.code, 'fecha': fecha})
        res = self.h('BACK', 'HORA', {
            'servicio_code': self.servicio.code, 'fecha': fecha})
        self.assertEqual(res['screen'], 'HORA')
        self.assertTrue(res['data']['horas'])


class TestFlowWebFallback(FlowAgentCase):
    """WhatsApp Web pierde el submit de HORA y reenvía el data_exchange de
    SERVICIO (bug del cliente de Meta). Detectamos el bucle y encaminamos al
    funnel de listas, sin obligar a cambiar de dispositivo."""

    def _hasta_hora(self):
        fecha_screen = self._pantalla_fecha()
        fecha = self._fecha_disponible(fecha_screen)
        return self.h('data_exchange', 'FECHA',
                      {'servicio_code': self.servicio.code, 'fecha': fecha})

    def test_servicio_tras_hora_detecta_bucle_web(self):
        hora = self._hasta_hora()
        self.assertEqual(hora['screen'], 'HORA')
        self.assertTrue(self.session.flow_seen_hora)
        res = self.h('data_exchange', 'SERVICIO',
                     {'servicio_code': self.servicio.code})
        self.assertEqual(res['screen'], 'ERROR_SESION')
        self.assertIn('agendar', res['data']['mensaje'])
        self.assertTrue(self.session.flow_web_incompat)

    def test_back_a_servicio_no_falsea_el_bucle(self):
        self._hasta_hora()
        self.h('BACK', 'SERVICIO', {})   # _init resetea flow_seen_hora
        self.assertFalse(self.session.flow_seen_hora)
        res = self.h('data_exchange', 'SERVICIO',
                     {'servicio_code': self.servicio.code})
        self.assertEqual(res['screen'], 'FECHA')
        self.assertFalse(self.session.flow_web_incompat)
