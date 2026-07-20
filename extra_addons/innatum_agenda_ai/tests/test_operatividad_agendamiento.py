# -*- coding: utf-8 -*-
"""MEDICIÓN de operatividad del agendamiento determinista.

No es un test de aprobación: es un BANCO DE MEDIDA. Dispara una matriz de
entradas realistas contra `process_message` SIN proveedor LLM configurado y
clasifica cada respuesta en:

  DET     → determinista: hay `fast_path` y el paciente recibe texto/botones
  MUDO    → el paciente NO recibe nada (response_text vacío sin skip_send)
  LLM     → se escapó al LLM (sin fast_path) → no determinista

Sin proveedor activo, la rama LLM devuelve error='no_active_provider', que
es justamente el marcador que necesitamos para contarla.

El resultado se imprime en el log como tabla + porcentajes.
"""
import logging
from datetime import datetime, timedelta

from .common_wa_fase2 import Fase2Case

_logger = logging.getLogger(__name__)


class OperabilityBench(Fase2Case):

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.Primitives = self.env['innatum.agenda.scheduling.primitives']
        self.Av = self.env['innatum.agenda.availability'].sudo()
        self._wa_seq = 0
        self._wamid_seq = 0

    # -- utilidades ---------------------------------------------------

    def _slots(self):
        dur = int(self.servicio.duracion or 30)
        return self.Av.free_slots(
            self.colaboradora, self.servicio, datetime.utcnow(),
            datetime.utcnow() + timedelta(days=21),
            duration_min=dur, granularity_min=dur)

    def _token(self):
        s = self._slots()
        self.assertTrue(s, 'fixture sin huecos')
        return 'D|%d|%s' % (self.colaboradora.id,
                            s[0].strftime('%Y-%m-%dT%H:%M:%S'))

    def _fecha_con_cupo(self):
        r = self.Primitives.summarize_schedule(
            self.servicio.code, company=self.company)
        f = r['proximas_fechas_con_cupo']
        self.assertTrue(f, 'fixture sin fechas con cupo')
        return f[-1]['fecha_iso']

    def _nueva_sesion(self, state='menu_principal', partner=True,
                      servicio=False):
        self._wa_seq += 1
        s = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '59399%06d' % self._wa_seq,
            'partner_id': self.paciente.id if partner else False,
        })
        if state != 'nueva':
            s.action_set_state(state)
        if servicio:
            s.current_servicio_code = self.servicio.code
        return s

    def _wamid(self):
        self._wamid_seq += 1
        return 'W_BENCH_%d' % self._wamid_seq

    def _clasificar(self, res):
        """DET / MUDO / LLM a partir de la respuesta de process_message."""
        txt = (res.get('response_text') or '').strip()
        tiene_payload = bool(res.get('meta_payload'))
        if res.get('error') == 'no_active_provider':
            return 'LLM'
        if res.get('skip_send'):
            return 'DET'          # silencio intencional (dedup, cooldown)
        if not txt and not tiene_payload:
            return 'MUDO'
        if not res.get('fast_path'):
            return 'LLM'
        return 'DET'

    def _correr(self, casos):
        """casos: lista de (etiqueta, session, texto). Devuelve resultados."""
        out = []
        for etiqueta, session, texto in casos:
            try:
                res = self.Agent.process_message(
                    session, texto, wamid=self._wamid())
                clase = self._clasificar(res)
                detalle = (res.get('response_text') or '')[:60].replace(
                    '\n', ' ')
            except Exception as e:
                clase = 'EXCEPCION'
                detalle = '%s: %s' % (type(e).__name__, str(e)[:50])
            out.append((etiqueta, clase, detalle))
        return out

    def _reportar(self, titulo, resultados):
        total = len(resultados)
        cuenta = {}
        for _e, c, _d in resultados:
            cuenta[c] = cuenta.get(c, 0) + 1
        _logger.info('')
        _logger.info('===== BENCH: %s (%d casos) =====', titulo, total)
        for etiqueta, clase, detalle in resultados:
            marca = {'DET': 'OK  ', 'MUDO': 'MUDO', 'LLM': 'LLM ',
                     'EXCEPCION': 'EXC '}.get(clase, '??  ')
            _logger.info('  [%s] %-42s | %s', marca, etiqueta, detalle)
        det = cuenta.get('DET', 0)
        _logger.info('  --> DET=%d MUDO=%d LLM=%d EXC=%d | determinista=%.1f%%',
                     det, cuenta.get('MUDO', 0), cuenta.get('LLM', 0),
                     cuenta.get('EXCEPCION', 0), 100.0 * det / total)
        _logger.info('')
        return cuenta, total


class TestBenchBotones(OperabilityBench):
    """Bloque 1: el camino por BOTONES (lo que el sistema mismo ofrece).
    Todo lo que el agente ofrece como botón DEBERÍA ser 100% determinista:
    es una superficie cerrada que el propio sistema generó."""

    def test_bench_botones(self):
        fecha = self._fecha_con_cupo()
        token = self._token()
        turno = self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': self._slots()[-1],
            'state': 'reserved',
        })
        casos = [
            ('menu:agendar', self._nueva_sesion(), 'menu:agendar'),
            ('menu:info', self._nueva_sesion(), 'menu:info'),
            ('menu:reagendar', self._nueva_sesion(), 'menu:reagendar'),
            ('menu:cancelar', self._nueva_sesion(), 'menu:cancelar'),
            ('menu:otra_fecha', self._nueva_sesion(), 'menu:otra_fecha'),
            ('servicio:CODE', self._nueva_sesion(),
             'servicio:%s' % self.servicio.code),
            ('fecha: con cupo', self._nueva_sesion(servicio=True),
             'fecha:%s' % fecha),
            ('periodo:AM', self._nueva_sesion(servicio=True),
             'periodo:AM:%s:%s' % (self.servicio.code, fecha)),
            ('periodo:NIGHT (sin cupo)', self._nueva_sesion(servicio=True),
             'periodo:NIGHT:%s:%s' % (self.servicio.code, fecha)),
            ('slot:TOKEN', self._nueva_sesion(servicio=True),
             'slot:%s' % token),
            ('info_turno:N', self._nueva_sesion(), 'info_turno:%d' % turno.id),
            ('cancel_turno:N', self._nueva_sesion(),
             'cancel_turno:%d' % turno.id),
            ('reagendar_turno:N', self._nueva_sesion(),
             'reagendar_turno:%d' % turno.id),
            ('ident:yes:N', self._nueva_sesion(state='confirmando_identidad'),
             'ident:yes:%d' % self.paciente.id),
            ('ident:no', self._nueva_sesion(state='confirmando_identidad'),
             'ident:no'),
        ]
        cuenta, total = self._reportar('BOTONES (superficie cerrada)',
                                       self._correr(casos))
        self.assertEqual(
            cuenta.get('DET', 0), total,
            'Los botones que el propio sistema ofrece deben ser 100%% '
            'deterministas. Medido: %s' % cuenta)


class TestBenchTextoLibre(OperabilityBench):
    """Bloque 2: TEXTO LIBRE realista del paciente. Aquí sí es esperable
    que parte caiga al LLM; lo que medimos es CUÁNTO y si algo queda MUDO."""

    def test_bench_texto_libre(self):
        casos = [
            ('hola', self._nueva_sesion(), 'hola'),
            ('buenas tardes', self._nueva_sesion(), 'buenas tardes'),
            ('quiero agendar una cita', self._nueva_sesion(),
             'quiero agendar una cita'),
            ('necesito un turno', self._nueva_sesion(), 'necesito un turno'),
            ('quiero sacar una cita porfa', self._nueva_sesion(),
             'quiero sacar una cita porfa'),
            ('mis citas', self._nueva_sesion(), 'mis citas'),
            ('cancelar mi cita', self._nueva_sesion(), 'cancelar mi cita'),
            ('reagendar', self._nueva_sesion(), 'reagendar'),
            ('Endodoncia', self._nueva_sesion(), 'Endodoncia'),
            ('quiero endodoncia', self._nueva_sesion(), 'quiero endodoncia'),
            ('el viernes', self._nueva_sesion(servicio=True), 'el viernes'),
            ('manana', self._nueva_sesion(servicio=True), 'mañana'),
            ('a las 10 de la manana', self._nueva_sesion(servicio=True),
             'a las 10 de la mañana'),
            ('si, para mi', self._nueva_sesion(state='confirmando_paciente'),
             'sí, para mí'),
            ('cuanto cuesta', self._nueva_sesion(), 'cuánto cuesta'),
            ('donde quedan', self._nueva_sesion(), 'dónde quedan'),
            ('gracias', self._nueva_sesion(), 'gracias'),
            ('ok', self._nueva_sesion(), 'ok'),
        ]
        cuenta, total = self._reportar('TEXTO LIBRE del paciente',
                                       self._correr(casos))
        self.assertEqual(
            cuenta.get('MUDO', 0), 0,
            'Ningún texto del paciente debe dejar al agente mudo. '
            'Medido: %s' % cuenta)


class TestBenchDegradado(OperabilityBench):
    """Bloque 3: entradas DEGRADADAS — botones viejos, datos sin cupo,
    tokens corruptos. Es el escenario donde el sistema debe GUIAR, no
    quedarse mudo ni escaparse al LLM."""

    def test_bench_degradado(self):
        ayer = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
        lejos = (datetime.utcnow() + timedelta(days=400)).strftime('%Y-%m-%d')
        casos = [
            ('fecha: ayer (botón viejo)', self._nueva_sesion(servicio=True),
             'fecha:%s' % ayer),
            ('fecha: +400d (sin cupo)', self._nueva_sesion(servicio=True),
             'fecha:%s' % lejos),
            ('fecha: sin servicio en sesion', self._nueva_sesion(),
             'fecha:%s' % self._fecha_con_cupo()),
            ('fecha: formato invalido', self._nueva_sesion(servicio=True),
             'fecha:2026-13-45'),
            ('servicio: inexistente', self._nueva_sesion(),
             'servicio:NO_EXISTE'),
            ('slot: token corrupto', self._nueva_sesion(servicio=True),
             'slot:D|abc|xyz'),
            ('slot: prof inexistente', self._nueva_sesion(servicio=True),
             'slot:D|999999|2026-08-01T14:00:00'),
            ('turno: inexistente', self._nueva_sesion(), 'turno:999999'),
            ('info_turno: inexistente', self._nueva_sesion(),
             'info_turno:999999'),
            ('book_for:self sin pendiente', self._nueva_sesion(),
             'book_for:self'),
            ('solo emojis', self._nueva_sesion(), '😀😀'),
            ('texto larguisimo', self._nueva_sesion(), 'a' * 600),
        ]
        resultados = self._correr(casos)
        # Caso aparte: quitar operadores AFECTA a todo el tenant, así que se
        # corre al final. (Antes se limpiaba antes de _correr y contaminaba
        # los 12 casos anteriores con "No hay profesionales para X".)
        self.servicio.operador_ids = [(5, 0, 0)]
        resultados += self._correr([
            ('servicio sin operadores', self._nueva_sesion(),
             'servicio:%s' % self.servicio.code),
        ])
        cuenta, total = self._reportar('DEGRADADO (botones viejos / sin cupo)',
                                       resultados)
        self.assertEqual(
            cuenta.get('MUDO', 0), 0,
            'En estado degradado el agente debe GUIAR, nunca quedarse mudo. '
            'Medido: %s' % cuenta)


class TestBenchJourneys(OperabilityBench):
    """Bloque 4: JOURNEYS completos de punta a punta. Mide el indicador que
    de verdad importa al negocio: ¿termina el paciente con una cita?"""

    def _journey_botones(self):
        s = self._nueva_sesion(state='nueva')
        self.Agent.process_message(s, 'hola', wamid=self._wamid())
        self.Agent.process_message(
            s, 'ident:yes:%d' % self.paciente.id, wamid=self._wamid())
        self.Agent.process_message(s, 'menu:agendar', wamid=self._wamid())
        self.Agent.process_message(
            s, 'servicio:%s' % self.servicio.code, wamid=self._wamid())
        self.Agent.process_message(
            s, 'fecha:%s' % self._fecha_con_cupo(), wamid=self._wamid())
        self.Agent.process_message(
            s, 'slot:%s' % self._token(), wamid=self._wamid())
        return self.Agent.process_message(
            s, 'book_for:self', wamid=self._wamid())

    def _journey_texto(self):
        s = self._nueva_sesion(state='nueva')
        self.Agent.process_message(s, 'hola', wamid=self._wamid())
        self.Agent.process_message(
            s, 'ident:yes:%d' % self.paciente.id, wamid=self._wamid())
        self.Agent.process_message(
            s, 'quiero agendar una cita', wamid=self._wamid())
        self.Agent.process_message(s, 'Endodoncia', wamid=self._wamid())
        self.Agent.process_message(
            s, 'fecha:%s' % self._fecha_con_cupo(), wamid=self._wamid())
        self.Agent.process_message(
            s, 'slot:%s' % self._token(), wamid=self._wamid())
        return self.Agent.process_message(
            s, 'book_for:self', wamid=self._wamid())

    def test_bench_journeys(self):
        resultados = []
        antes = self.Turno.search_count([])
        r1 = self._journey_botones()
        ok1 = self.Turno.search_count([]) == antes + 1
        resultados.append(('journey botones puros',
                           'DET' if ok1 else 'FALLO',
                           (r1.get('response_text') or '')[:60]))

        antes = self.Turno.search_count([])
        r2 = self._journey_texto()
        ok2 = self.Turno.search_count([]) == antes + 1
        resultados.append(('journey texto libre + botones',
                           'DET' if ok2 else 'FALLO',
                           (r2.get('response_text') or '')[:60]))

        self._reportar('JOURNEYS end-to-end', resultados)
        self.assertTrue(ok1, 'El journey por botones no creó el turno.')
        self.assertTrue(ok2, 'El journey con texto libre no creó el turno.')


class TestBenchBucleReagendar(OperabilityBench):
    """El id `reagendar_turno:N` no tiene handler, PERO el texto contiene la
    subcadena 'reagendar', así que `_match_menu_keyword` lo captura y
    re-muestra la MISMA lista. Resultado: bucle infinito, no fallback."""

    def test_reagendar_es_un_bucle(self):
        turno = self.Turno.create({
            'company_id': self.company.id,
            'professional_id': self.colaboradora.id,
            'servicio_id': self.servicio.id,
            'servicio_ids': [(6, 0, self.servicio.ids)],
            'partner_id': self.paciente.id,
            'date_start': self._slots()[-1],
            'state': 'reserved',
        })
        s = self._nueva_sesion()
        r1 = self.Agent.process_message(s, 'menu:reagendar',
                                        wamid=self._wamid())
        vueltas = []
        for _ in range(3):
            r = self.Agent.process_message(
                s, 'reagendar_turno:%d' % turno.id, wamid=self._wamid())
            vueltas.append(r.get('fast_path'))
        _logger.info('BUCLE reagendar: inicial=%s vueltas=%s',
                     r1.get('fast_path'), vueltas)
        self.assertNotEqual(
            vueltas, [r1.get('fast_path')] * 3,
            'BUCLE CONFIRMADO: tocar una cita en "Reagendar" devuelve siempre '
            'la misma lista (%s). El paciente no puede salir ni avanzar.'
            % vueltas)
