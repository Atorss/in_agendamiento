# -*- coding: utf-8 -*-
"""ESCENARIOS de agendamiento de punta a punta.

Simula conversaciones reales completas (no unidades sueltas): distintos
tipos de paciente, distintas formas de pedir, el bucle de WhatsApp Web y su
alternativa por listas. Cada escenario verifica el RESULTADO de negocio
(¿quedó la cita?) y la CALIDAD de lo que lee el paciente (idioma, sin
tecnicismos, siempre con próximo paso).
"""
import json
import logging
import time
from datetime import datetime, timedelta

from .common_wa_fase2 import Fase2Case
from ..models.wa_flow_token import get_flow_token_secret, make_flow_token

_logger = logging.getLogger(__name__)

# Nombres de día/mes en inglés que NUNCA deben llegar al paciente.
_INGLES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
           'Saturday', 'Sunday', 'January', 'February', 'March', 'April',
           'June', 'July', 'August', 'September', 'October', 'November',
           'December')


class EscenarioCase(Fase2Case):

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.Primitives = self.env['innatum.agenda.scheduling.primitives']
        self.Av = self.env['innatum.agenda.availability'].sudo()
        self._n = 0
        self._w = 0
        self._traza = []
        self._titulo = 'sin titulo'

    def _wamid(self):
        self._w += 1
        return 'W_ESC_%d_%d' % (id(self), self._w)

    def _sesion(self, partner=None, state='nueva'):
        self._n += 1
        s = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '5939880%05d' % self._n,
            'partner_id': (partner.id if partner else False),
        })
        if state != 'nueva':
            s.action_set_state(state)
        return s

    def _slots(self):
        dur = int(self.servicio.duracion or 30)
        return self.Av.free_slots(
            self.colaboradora, self.servicio, datetime.utcnow(),
            datetime.utcnow() + timedelta(days=21),
            duration_min=dur, granularity_min=dur)

    def _token(self, idx=0):
        s = self._slots()
        self.assertTrue(s, 'fixture sin huecos')
        return 'D|%d|%s' % (self.colaboradora.id,
                            s[idx].strftime('%Y-%m-%dT%H:%M:%S'))

    def _fecha_con_cupo(self):
        r = self.Primitives.summarize_schedule(
            self.servicio.code, company=self.company)
        return r['proximas_fechas_con_cupo'][-1]['fecha_iso']

    def _decir(self, session, texto, tipo='text'):
        """Envía un mensaje y devuelve la respuesta, guardando la traza."""
        res = self.Agent.process_message(
            session, texto, message_type=tipo, wamid=self._wamid())
        self._traza.append((texto[:40], (res.get('response_text') or '')[:70]))
        return res

    def _abrir_traza(self, titulo):
        self._traza = []
        self._titulo = titulo

    def _log_traza(self):
        _logger.info('')
        _logger.info('===== ESCENARIO: %s =====', self._titulo)
        for entrada, salida in self._traza:
            _logger.info('  👤 %-40s', entrada)
            _logger.info('  🤖 %s', salida.replace('\n', ' | '))
        _logger.info('')

    def _assert_sin_ingles(self, res, contexto=''):
        txt = res.get('response_text') or ''
        for palabra in _INGLES:
            self.assertNotIn(
                palabra, txt,
                'Fecha en INGLÉS ("%s") en el mensaje al paciente%s: %s'
                % (palabra, contexto, txt[:120]))

    def _assert_guia(self, res, contexto=''):
        """El paciente siempre debe recibir algo y con próximo paso."""
        txt = (res.get('response_text') or '').strip()
        self.assertTrue(
            txt or res.get('meta_payload'),
            'Respuesta MUDA%s' % contexto)


class TestIdiomaFechas(EscenarioCase):
    """Las fechas que lee el paciente deben ir en ESPAÑOL. `%A` crudo
    devuelve 'Monday' con el locale C del contenedor."""

    def _turno(self):
        return self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': self._slots()[-1],
            'state': 'reserved',
        })

    def test_detalle_de_cita_en_espanol(self):
        s = self._sesion(self.paciente, 'menu_principal')
        self._abrir_traza('idioma: detalle de cita')
        res = self._decir(s, 'info_turno:%d' % self._turno().id)
        self._log_traza()
        self._assert_sin_ingles(res, ' (detalle de cita)')

    def test_confirmar_cancelacion_en_espanol(self):
        s = self._sesion(self.paciente, 'menu_principal')
        res = self._decir(s, 'cancel_turno:%d' % self._turno().id)
        self._assert_sin_ingles(res, ' (confirmar cancelación)')

    def test_confirmar_reagendar_en_espanol(self):
        s = self._sesion(self.paciente, 'menu_principal')
        res = self._decir(s, 'reagendar_turno:%d' % self._turno().id)
        self._assert_sin_ingles(res, ' (confirmar reagendar)')

    def test_mis_citas_en_espanol(self):
        self._turno()
        s = self._sesion(self.paciente, 'menu_principal')
        res = self._decir(s, 'menu:info')
        filas = json.dumps(res.get('meta_payload') or {}, ensure_ascii=False)
        for palabra in _INGLES:
            self.assertNotIn(palabra, filas,
                             'Fecha en INGLÉS en la lista de citas: %s'
                             % filas[:200])

    def test_reserva_confirmada_en_espanol(self):
        s = self._sesion(self.paciente, 'confirmando_paciente')
        s.current_servicio_code = self.servicio.code
        s.pending_slot_token = self._token()
        res = self._decir(s, 'book_for:self')
        self.assertIn('Cita reservada', res['response_text'])
        self._assert_sin_ingles(res, ' (resumen de reserva)')


class TestEscenarioPacienteConocido(EscenarioCase):
    """Paciente recurrente, camino por botones. El caso mayoritario."""

    def test_agenda_completo_por_botones(self):
        s = self._sesion()
        self._abrir_traza('paciente conocido, botones')
        antes = self.Turno.search_count([])
        self._decir(s, 'hola')
        self._decir(s, 'ident:yes:%d' % self.paciente.id)
        self._decir(s, 'menu:agendar')
        self._decir(s, 'servicio:%s' % self.servicio.code)
        self._decir(s, 'fecha:%s' % self._fecha_con_cupo())
        self._decir(s, 'slot:%s' % self._token())
        res = self._decir(s, 'book_for:self')
        self._log_traza()
        self.assertEqual(self.Turno.search_count([]), antes + 1)
        self.assertIn('Cita reservada', res['response_text'])
        self.assertIn(s.state, ('confirmada', 'pendiente_pago'))
        self._assert_sin_ingles(res)


class TestEscenarioTodoEnTexto(EscenarioCase):
    """Paciente que NO toca botones: escribe todo. Antes se perdía en el LLM."""

    def test_agenda_escribiendo(self):
        s = self._sesion(self.paciente, 'menu_principal')
        self._abrir_traza('paciente escribe todo')
        antes = self.Turno.search_count([])
        r1 = self._decir(s, 'buenas, necesito un turno')
        self._assert_guia(r1, ' (pedir turno en palabras)')
        r2 = self._decir(s, 'endodoncia')
        self._assert_guia(r2, ' (servicio en palabras)')
        r3 = self._decir(s, 'mañana')
        self._assert_guia(r3, ' (día en palabras)')
        # El horario sí llega por botón (la hora la ofrece el sistema).
        self._decir(s, 'slot:%s' % self._token())
        res = self._decir(s, 'sí, para mí')
        self._log_traza()
        self.assertEqual(self.Turno.search_count([]), antes + 1,
                         'el paciente que escribe debe poder agendar')
        self.assertIn('Cita reservada', res['response_text'])


class TestEscenarioParaTercero(EscenarioCase):
    """Reserva para otra persona (mamá que agenda al hijo)."""

    def test_agenda_para_tercero(self):
        s = self._sesion(self.paciente, 'menu_principal')
        s.current_servicio_code = self.servicio.code
        self._abrir_traza('reserva para un tercero')
        antes = self.Turno.search_count([])
        self._decir(s, 'slot:%s' % self._token())
        r = self._decir(s, 'book_for:other')
        self.assertEqual(s.state, 'esperando_cedula_tercero')
        self._assert_guia(r, ' (pide cédula del tercero)')
        self._decir(s, '1710034065')            # cédula EC válida
        res = self._decir(s, 'Mateo Pérez')
        self._log_traza()
        self.assertEqual(self.Turno.search_count([]), antes + 1)
        turno = self.Turno.search([], order='id desc', limit=1)
        self.assertNotEqual(turno.partner_id.id, self.paciente.id,
                            'el turno debe quedar a nombre del tercero')
        self._assert_sin_ingles(res)


class TestEscenarioCancelaYReagenda(EscenarioCase):
    """El paciente cambia de opinión: cancela una y reagenda otra."""

    def _turno_lejano(self):
        limite = datetime.utcnow() + timedelta(hours=72)
        lejanos = [x for x in self._slots() if x > limite]
        self.assertTrue(lejanos)
        return self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': lejanos[0],
            'state': 'reserved',
        })

    def test_cancela_su_cita(self):
        turno = self._turno_lejano()
        s = self._sesion(self.paciente, 'menu_principal')
        self._abrir_traza('cancelación')
        self._decir(s, 'menu:cancelar')
        self._decir(s, 'cancel_turno:%d' % turno.id)
        res = self._decir(s, 'confirm_cancel:%d' % turno.id)
        self._log_traza()
        self.assertEqual(turno.state, 'cancelled')
        self.assertIn('cancelada', res['response_text'].lower())
        self._assert_sin_ingles(res)

    def test_reagenda_sin_bucle(self):
        turno = self._turno_lejano()
        s = self._sesion(self.paciente, 'menu_principal')
        self._abrir_traza('reagendar')
        self._decir(s, 'menu:reagendar')
        r1 = self._decir(s, 'reagendar_turno:%d' % turno.id)
        self.assertEqual(r1.get('fast_path'), 'ask_reagendar',
                         'debe pedir confirmación, no repetir la lista')
        r2 = self._decir(s, 'confirm_reagendar:%d' % turno.id)
        self._log_traza()
        self.assertEqual(turno.state, 'cancelled',
                         'reagendar libera el horario anterior')
        self.assertEqual(s.current_servicio_code, self.servicio.code,
                         'debe conservar el servicio para no repreguntarlo')
        self._assert_guia(r2, ' (tras confirmar reagendar)')
        self._assert_sin_ingles(r2)


class TestEscenarioWhatsAppWeb(EscenarioCase):
    """El bug de WhatsApp Web y su alternativa.

    WhatsApp Web pierde el submit de la pantalla HORA y reenvía el
    data_exchange de SERVICIO. El endpoint detecta el bucle, marca la sesión
    y el agente pasa al funnel de listas (que sí funciona en Web). Este
    escenario recorre TODO ese camino hasta que la cita queda creada.
    """

    def setUp(self):
        super().setUp()
        self.FlowAgent = self.env['innatum.wa.flow.agent']
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_wa.flows_enabled', 'True')
        self.company.wa_flow_id = '111222333'
        kp = self.env['innatum.wa.flow.keypair'].create(
            {'company_id': self.company.id})
        kp.action_generate()

    def _primer_dia_habil(self, res_fecha):
        """Primer día de la ventana del CalendarPicker que no esté marcado
        como no disponible (mismo criterio que los tests del Flow)."""
        d = datetime.strptime(res_fecha['data']['min_date'], '%Y-%m-%d').date()
        max_d = datetime.strptime(
            res_fecha['data']['max_date'], '%Y-%m-%d').date()
        no_hay = set(res_fecha['data']['unavailable_dates'])
        while d <= max_d:
            if d.strftime('%Y-%m-%d') not in no_hay:
                return d.strftime('%Y-%m-%d')
            d += timedelta(days=1)
        self.fail('No hay días disponibles en la ventana del Flow')

    def _flow_token(self, session):
        return make_flow_token(session.id,
                               get_flow_token_secret(self.env), time.time())

    def test_web_cicla_y_se_reserva_por_listas(self):
        s = self._sesion(self.paciente, 'menu_principal')
        self._abrir_traza('WhatsApp Web: bucle → listas')
        antes = self.Turno.search_count([])

        # 1) En Web el agente igual ofrece el Flow (no sabe el dispositivo).
        r = self._decir(s, 'menu:agendar')
        self.assertEqual(r.get('fast_path'), 'flow_agendar')

        # 2) El Flow avanza hasta HORA (esto sí ocurre en Web).
        tok = self._flow_token(s)
        self.FlowAgent.handle(s, 'INIT', None, {}, tok)
        r_fecha = self.FlowAgent.handle(
            s, 'data_exchange', 'SERVICIO',
            {'servicio_code': self.servicio.code}, tok)
        self.assertEqual(r_fecha.get('screen'), 'FECHA')
        # La pantalla HORA necesita servicio_code Y fecha: el cliente de Flow
        # arrastra los campos ya elegidos en cada data_exchange.
        dia = self._primer_dia_habil(r_fecha)
        r_hora = self.FlowAgent.handle(
            s, 'data_exchange', 'FECHA',
            {'servicio_code': self.servicio.code, 'fecha': dia}, tok)
        self.assertEqual(r_hora.get('screen'), 'HORA')
        self.assertTrue(s.flow_seen_hora, 'debe quedar marcado el paso por HORA')

        # 3) BUG de Web: en vez del submit de HORA reenvía SERVICIO.
        r_bug = self.FlowAgent.handle(
            s, 'data_exchange', 'SERVICIO',
            {'servicio_code': self.servicio.code}, tok)
        self.assertNotEqual(
            r_bug.get('screen'), 'FECHA',
            'el bucle debe cortarse, no volver al calendario')
        self.assertTrue(s.flow_web_incompat,
                        'la sesión debe quedar marcada como Web-incompatible')

        # 4) Alternativa: el paciente escribe "agendar" y va por LISTAS.
        r_lista = self._decir(s, 'agendar')
        self.assertNotEqual(
            r_lista.get('fast_path'), 'flow_agendar',
            'una sesión Web-incompatible NO debe recibir el Flow otra vez')
        self._assert_guia(r_lista, ' (fallback a listas)')

        # 5) Y completa la reserva por el funnel de listas.
        self._decir(s, 'servicio:%s' % self.servicio.code)
        self._decir(s, 'fecha:%s' % self._fecha_con_cupo())
        self._decir(s, 'slot:%s' % self._token())
        res = self._decir(s, 'book_for:self')
        self._log_traza()
        self.assertEqual(self.Turno.search_count([]), antes + 1,
                         'el paciente de Web debe terminar con su cita')
        self.assertIn('Cita reservada', res['response_text'])
        self._assert_sin_ingles(res)

    def test_menu_nuevo_rehabilita_el_flow(self):
        """Tras el bucle, un menú nuevo debe volver a ofrecer el Flow: el
        paciente puede haber cambiado al móvil."""
        s = self._sesion(self.paciente, 'menu_principal')
        s.flow_web_incompat = True
        self._decir(s, 'hola')
        self.assertFalse(s.flow_web_incompat,
                         'el menú principal debe limpiar el flag')
        r = self._decir(s, 'menu:agendar')
        self.assertEqual(r.get('fast_path'), 'flow_agendar')


class TestEscenarioColisionYReintento(EscenarioCase):
    """Dos pacientes pelean el mismo horario: el segundo debe recibir un
    mensaje humano y poder reintentar en otro horario."""

    def test_segundo_paciente_reintenta(self):
        otro = self.env['res.partner'].create({
            'name': 'Ana Torres', 'company_id': self.company.id,
            'mobile': '0955443322'})
        # Capturar AMBOS tokens ANTES de reservar: tras la primera reserva
        # ese hueco desaparece de free_slots y _token(0) devolvería otro
        # horario distinto — no habría colisión y el test no probaría nada.
        token_disputado = self._token(0)
        token_alternativo = self._token(1)
        s1 = self._sesion(self.paciente, 'confirmando_paciente')
        s1.current_servicio_code = self.servicio.code
        s1.pending_slot_token = token_disputado
        self._abrir_traza('colisión de horario')
        self._decir(s1, 'book_for:self')

        s2 = self._sesion(otro, 'confirmando_paciente')
        s2.current_servicio_code = self.servicio.code
        s2.pending_slot_token = token_disputado     # MISMO horario
        r = self._decir(s2, 'book_for:self')
        self.assertNotIn('Cita reservada', r['response_text'])
        self.assertNotIn('TRN/', r['response_text'],
                         'no debe filtrar la referencia del turno ajeno')
        self.assertNotIn('constraint', r['response_text'].lower())
        self._assert_guia(r, ' (colisión)')

        # …y puede reservar OTRO horario sin reiniciar la conversación.
        antes = self.Turno.search_count([])
        s2.pending_slot_token = token_alternativo
        r2 = self._decir(s2, 'book_for:self')
        self._log_traza()
        self.assertEqual(self.Turno.search_count([]), antes + 1)
        self.assertIn('Cita reservada', r2['response_text'])


class TestEscenarioPacienteNuevo(EscenarioCase):
    """Número desconocido: identidad por cédula y luego agenda."""

    def test_nuevo_se_identifica_y_agenda(self):
        s = self._sesion()
        self._abrir_traza('paciente nuevo')
        r = self._decir(s, 'hola')
        self.assertEqual(s.state, 'esperando_cedula')
        self._assert_guia(r, ' (pide cédula)')
        self._decir(s, '1710034065')
        res = self._decir(s, 'Lucía Andrade')
        self._log_traza()
        self.assertTrue(s.partner_id, 'debe quedar identificado')
        self._assert_guia(res, ' (tras identificarse)')
        self._assert_sin_ingles(res)
