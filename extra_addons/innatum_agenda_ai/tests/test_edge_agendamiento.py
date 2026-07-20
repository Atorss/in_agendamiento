# -*- coding: utf-8 -*-
"""AUDITORÍA: casos edge del agendamiento por la vía determinista.

Cada test documenta una HIPÓTESIS de bug y la confirma/descarta con datos.
Los que fallan son bugs reales pendientes de arreglo (ver reporte).
"""
from datetime import datetime, timedelta

from .common_wa_fase2 import Fase2Case


class EdgeCase(Fase2Case):

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.Primitives = self.env['innatum.agenda.scheduling.primitives']
        self.Av = self.env['innatum.agenda.availability'].sudo()

    def _slots(self, dias=21):
        dur = int(self.servicio.duracion or 30)
        return self.Av.free_slots(
            self.colaboradora, self.servicio, datetime.utcnow(),
            datetime.utcnow() + timedelta(days=dias),
            duration_min=dur, granularity_min=dur)

    def _token(self, dt=None):
        if dt is None:
            slots = self._slots()
            self.assertTrue(slots, 'fixture directa sin huecos libres')
            dt = slots[0]
        return 'D|%d|%s' % (self.colaboradora.id,
                            dt.strftime('%Y-%m-%dT%H:%M:%S'))

    def _slot_lejano(self, min_horas=72):
        """Hueco libre a >72h: evita que la regla de preaviso mínimo de
        cancelación (24h) enmascare lo que se quiere probar."""
        limite = datetime.utcnow() + timedelta(hours=min_horas)
        lejanos = [s for s in self._slots() if s > limite]
        self.assertTrue(lejanos, 'fixture sin huecos a >%dh' % min_horas)
        return lejanos[0]

    def _turno_real(self, partner=None, state='reserved', dt=None):
        """Turno en un hueco laborable real (en directa hay constraint de
        horario laboral, así que no vale cualquier datetime)."""
        slots = self._slots()
        self.assertTrue(slots, 'fixture directa sin huecos libres')
        if dt is not None:
            slots = [dt]
        return self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': (partner or self.paciente).id,
            'date_start': slots[0],
            'state': state,
        })

    def _sesion(self, wa_from, partner=None, state='menu_principal'):
        s = self.Session.create({
            'company_id': self.company.id, 'wa_from': wa_from,
            'partner_id': (partner or self.paciente).id,
        })
        s.action_set_state(state)
        return s


class TestEdgeReagendar(EdgeCase):
    """H1: el menú 'Reagendar' lista filas con id `reagendar_turno:N`, pero
    NO existe handler ni entrada en _RE_ANY_BUTTON_ID → el tap cae al LLM."""

    def test_boton_reagendar_turno_tiene_handler(self):
        turno = self._turno_real()
        session = self._sesion('593990010001')
        res = self.Agent._handle_known_button_id(
            'reagendar_turno:%d' % turno.id, session)
        self.assertIsNotNone(
            res, 'H1 CONFIRMADA: `reagendar_turno:N` no tiene handler; el tap '
                 'del menú Reagendar cae al LLM (callejón sin salida).')


class TestEdgeCancelIDOR(EdgeCase):
    """H2: `_execute_cancel` no valida propiedad; `cancelar_turno` solo la
    valida si la sesión TIENE partner. Una sesión sin partner (p.ej. tras
    `ident:no`, estado esperando_cedula) puede cancelar la cita de otro."""

    def test_sesion_sin_partner_no_cancela_cita_ajena(self):
        victima = self.env['res.partner'].create({
            'name': 'Víctima', 'company_id': self.company.id,
            'mobile': '0999888777',
        })
        # >72h: si no, la regla de preaviso mínimo bloquearía la cancelación
        # y el test pasaría por el motivo equivocado (falso negativo).
        turno = self._turno_real(partner=victima, dt=self._slot_lejano())
        atacante = self.Session.create({
            'company_id': self.company.id, 'wa_from': '593990020002',
        })
        atacante.action_set_state('esperando_cedula')   # sin partner_id
        self.Agent.process_message(
            atacante, 'confirm_cancel:%d' % turno.id, wamid='W_IDOR')
        self.assertNotEqual(
            turno.state, 'cancelled',
            'H2 CONFIRMADA (IDOR): una sesión sin identificar canceló la cita '
            'de otro paciente escribiendo confirm_cancel:<id>.')


class TestEdgeSlotPasado(EdgeCase):
    """H3: el token de slot no se revalida al reservar. Un botón viejo
    (tapeado al día siguiente) reserva un turno EN EL PASADO."""

    def test_token_en_el_pasado_es_rechazado(self):
        # Mismo día de semana y hora que un hueco válido, pero 7 días antes:
        # así cae DENTRO del horario laboral y lo único "malo" es que ya pasó.
        pasado = self._slots()[0] - timedelta(days=7)
        self.assertLess(pasado, datetime.utcnow())
        res = self.Primitives.reserve_existing(
            turno_id=self._token(pasado), partner_id=self.paciente.id,
            servicio_code=self.servicio.code, company=self.company)
        self.assertNotIn(
            'exito', res,
            'H3 CONFIRMADA: se creó un turno en el pasado (%s) desde un token '
            'de slot vencido.' % pasado)
        # No basta con que falle: debe fallar POR ser pasado, no por un
        # motivo accidental (si no, es un falso negativo de esta auditoría).
        self.assertIn(
            'pas', (res.get('error') or '').lower(),
            'H3-bis: el token vencido se rechaza, pero por un motivo '
            'colateral ("%s"), no por estar en el pasado. La protección es '
            'accidental.' % res.get('error'))


class TestEdgeProfesionalAjeno(EdgeCase):
    """H4: `reserve_directo` valida que el profesional sea del tenant, pero
    NO que preste el servicio. Un token tecleado con otro operador reserva
    con un profesional que no ofrece ese servicio."""

    def test_profesional_que_no_presta_el_servicio(self):
        # self.derivador NO está en servicio.operador_ids
        self.derivador.resource_calendar_id = \
            self.colaboradora.resource_calendar_id
        slots = self._slots()
        token = 'D|%d|%s' % (self.derivador.id,
                             slots[0].strftime('%Y-%m-%dT%H:%M:%S'))
        res = self.Primitives.reserve_existing(
            turno_id=token, partner_id=self.paciente.id,
            servicio_code=self.servicio.code, company=self.company)
        self.assertNotIn(
            'exito', res,
            'H4 CONFIRMADA: se reservó "%s" con %s, que no está en los '
            'operadores del servicio.' % (self.servicio.name,
                                          self.derivador.name))


class TestEdgeDobleReserva(EdgeCase):
    """H5: doble tap de `book_for:self` (dos wamid distintos) tras una
    reserva exitosa. El segundo debe dar un mensaje claro, no un error
    técnico ni una doble reserva."""

    def test_doble_tap_book_for_self(self):
        session = self._sesion('593990030003', state='confirmando_paciente')
        session.current_servicio_code = self.servicio.code
        session.pending_slot_token = self._token()
        antes = self.Turno.search_count([])
        self.Agent.process_message(session, 'book_for:self', wamid='W_D1')
        self.assertEqual(self.Turno.search_count([]), antes + 1)
        res2 = self.Agent.process_message(
            session, 'book_for:self', wamid='W_D2')
        self.assertEqual(
            self.Turno.search_count([]), antes + 1,
            'H5a: el doble tap creó DOS turnos.')
        txt = res2.get('response_text') or ''
        self.assertNotIn(
            'No tengo un turno pendiente', txt,
            'H5b CONFIRMADA: tras reservar OK, el segundo tap responde '
            '"No tengo un turno pendiente" (mensaje contradictorio). '
            'Debería decir "ya reservamos tu cita".')


class TestEdgeColisionSlot(EdgeCase):
    """H6: dos pacientes eligen el MISMO horario. El segundo debe recibir un
    mensaje amable, no el texto crudo del ValidationError con la referencia
    del turno del otro paciente (fuga de datos)."""

    def test_colision_no_filtra_datos_del_otro_turno(self):
        otro = self.env['res.partner'].create({
            'name': 'Otro Paciente', 'company_id': self.company.id,
            'mobile': '0977666555',
        })
        token = self._token()
        r1 = self.Primitives.reserve_existing(
            turno_id=token, partner_id=self.paciente.id,
            servicio_code=self.servicio.code, company=self.company)
        self.assertTrue(r1.get('exito'))
        r2 = self.Primitives.reserve_existing(
            turno_id=token, partner_id=otro.id,
            servicio_code=self.servicio.code, company=self.company)
        self.assertNotIn('exito', r2, 'doble reserva del mismo horario')
        err = r2.get('error', '')
        self.assertNotIn(
            r1['referencia'], err,
            'H6 CONFIRMADA: el error muestra la referencia del turno de otro '
            'paciente (%s) → fuga de datos + UX técnica.' % r1['referencia'])


class TestEdgeTruncado30(EdgeCase):
    """H7: `find_availability` corta a 30 slots ANTES de filtrar por período.
    Con agenda densa, el período de la tarde/noche aparece vacío aunque
    tenga cupo real."""

    def test_periodo_tarde_no_desaparece_por_truncado(self):
        # Turnos de 5 min: la jornada de la MAÑANA sola ya supera los 30
        # slots, así que bajo el bug los primeros 30 son todos AM y la tarde
        # desaparece por completo. Con 15 min (48 slots/día) el corte a 30
        # todavía dejaba tarde y el test no detectaba nada.
        self.servicio.duracion = 5.0
        # El calendario por defecto del fixture está en UTC: 08-17 UTC cae en
        # 03-12 hora local, así que NO habría slots PM que recuperar y el test
        # pasaría sin probar nada. Se fija el tz del calendario al del tenant
        # para que la jornada 08-17 abarque de verdad mañana Y tarde.
        cal = (self.colaboradora.resource_calendar_id
               or self.company.resource_calendar_id).sudo()
        cal.tz = 'America/Guayaquil'
        self.colaboradora.resource_id.sudo().tz = 'America/Guayaquil'
        summ = self.Primitives.summarize_schedule(
            self.servicio.code, company=self.company)
        fechas = summ['proximas_fechas_con_cupo']
        self.assertTrue(fechas)
        fecha = fechas[-1]['fecha_iso']
        todos = self.Primitives.find_availability(
            self.servicio.code, fecha=fecha, company=self.company)
        pm_filtrado = self.Primitives.find_availability(
            self.servicio.code, fecha=fecha, periodo='PM',
            company=self.company)
        # El fixture debe ser denso para que el corte a 30 sea relevante.
        self.assertGreaterEqual(
            todos.get('total_disponibles', 0), 30,
            'fixture insuficiente: se necesitan >=30 slots para probar el '
            'truncado')
        self.assertTrue(
            pm_filtrado.get('slots'),
            'H7 CONFIRMADA: con %d slots el corte a 30 dejó la tarde sin '
            'horarios (el cliente ve "no hay cupo" y sí lo hay).'
            % todos['total_disponibles'])
        self.assertTrue(
            all(s['periodo'] == 'PM' for s in pm_filtrado['slots']))


class TestEdgeTurnoAjenoInfo(EdgeCase):
    """H8: `turno:N` (modo planificada) hace browse sin validar tenant ni
    dueño antes de mostrar servicio y fecha en el mensaje."""

    def test_turno_de_otro_tenant_no_se_expone(self):
        otra_co = self.env['res.company'].create({'name': 'Clínica Rival'})
        plan = self.env['in_agenda.plan'].search([], limit=1)
        self.env['in_agenda.suscripcion'].create({
            'company_id': otra_co.id, 'plan_id': plan.id,
            'fecha_fin': '2099-12-31', 'state': 'active',
        })
        prof2 = self.env['hr.employee'].create({
            'name': 'Dr. Rival', 'company_id': otra_co.id})
        serv2 = self.env['innatum.agenda.servicio'].create({
            'name': 'Blanqueamiento VIP', 'company_id': otra_co.id,
            'duracion': 30.0})
        turno = self.Turno.create({
            'company_id': otra_co.id,
            'professional_id': prof2.id,
            'servicio_id': serv2.id,
            'servicio_ids': [(6, 0, serv2.ids)],
            'date_start': datetime.utcnow() + timedelta(days=4),
            'state': 'available',
        })
        session = self._sesion('593990040004')
        res = self.Agent.process_message(
            session, 'turno:%d' % turno.id, wamid='W_XT')
        self.assertNotIn(
            'Blanqueamiento VIP', res.get('response_text') or '',
            'H8 CONFIRMADA: turno:N expuso el servicio de OTRO tenant en el '
            'mensaje al paciente.')


class TestEdgeFechaPasada(EdgeCase):
    """H9: `fecha:YYYY-MM-DD` con una fecha ya pasada (botón viejo o texto
    tecleado) debe responder algo coherente, no una lista vacía muda."""

    def test_fecha_pasada_responde_mensaje_claro(self):
        session = self._sesion('593990050005')
        session.current_servicio_code = self.servicio.code
        ayer = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
        res = self.Agent.process_message(
            session, 'fecha:%s' % ayer, wamid='W_FP')
        self.assertTrue(
            (res.get('response_text') or '').strip(),
            'H9 CONFIRMADA: fecha pasada deja al agente mudo (respuesta '
            'vacía).')
