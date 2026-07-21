# -*- coding: utf-8 -*-
"""Ruteo por intención (Fase 1).

Dos niveles, deliberadamente separados:

1. RUTEO (estos tests): el clasificador se STUBEA. Se verifica que cada
   intención aterrice en el handler determinista correcto y que el LLM no
   redacte nunca. Es determinista y corre siempre.

2. CLASIFICACIÓN (golden set, `test_intent_golden.py`): mide la precisión
   del modelo real contra un corpus de frases. Necesita proveedor y NO corre
   en la suite normal.

Separarlos es lo que permite tener un LLM en la ruta de decisión sin perder
un banco determinista.
"""
from unittest.mock import patch

from .common_wa_fase2 import Fase2Case
from ..models.wa_intent_classifier import INTENTS, INTENT_TO_BUTTON


class IntentCase(Fase2Case):

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.Clasificador = self.env['innatum.wa.intent.classifier']
        self._n = 0

    def _sesion(self, state='menu_principal', partner=True):
        self._n += 1
        s = self.Session.create({
            'company_id': self.company.id,
            'wa_from': '59397770%04d' % self._n,
            'partner_id': self.paciente.id if partner else False,
        })
        s.action_set_state(state)
        return s

    def _con_intencion(self, intention, confidence=0.95):
        """Context manager: el clasificador devuelve siempre esa intención."""
        valor = ({'intention': intention, 'confidence': confidence}
                 if intention else None)
        return patch.object(
            type(self.Clasificador), 'classify',
            lambda self_, text, session=None: valor)

    def _decir(self, session, texto, wamid=None):
        return self.Agent.process_message(
            session, texto, wamid=wamid or ('W_INT_%d' % self._n))


class TestMapeoIntenciones(IntentCase):
    """Cada intención debe aterrizar en el handler determinista correcto."""

    def test_consulta_citas_muestra_citas_no_agendar(self):
        s = self._sesion()
        with self._con_intencion('consulta_citas'):
            # Texto SIN keyword: debe llegar al clasificador. (Con
            # "información de mis citas" gana la keyword antes, que también
            # es correcto, pero entonces no probaría esta ruta.)
            res = self._decir(s, 'a ver qué tengo pendiente por ahí',
                              'W_MAP_1')
        self.assertEqual(res.get('intent'), 'consulta_citas')
        self.assertNotIn('Agenda tu cita', res.get('response_text') or '')
        self.assertNotEqual(res.get('fast_path'), 'flow_agendar')

    def test_agenda_cita_entra_al_funnel(self):
        s = self._sesion()
        with self._con_intencion('agenda_cita'):
            res = self._decir(s, 'a ver si me consigues un espacio',
                              'W_MAP_2')
        self.assertEqual(res.get('intent'), 'agenda_cita')
        self.assertIn(res.get('fast_path'), ('menu:agendar', 'flow_agendar'))

    def test_cancela_cita_va_a_cancelar(self):
        s = self._sesion()
        with self._con_intencion('cancela_cita'):
            res = self._decir(s, 'ya no voy a poder ir', 'W_MAP_3')
        self.assertEqual(res.get('intent'), 'cancela_cita')

    def test_reagenda_cita_va_a_reagendar(self):
        s = self._sesion()
        with self._con_intencion('reagenda_cita'):
            res = self._decir(s, 'se me cruzó algo ese día', 'W_MAP_4')
        self.assertEqual(res.get('intent'), 'reagenda_cita')

    def test_todas_las_intenciones_tienen_ruta_definida(self):
        """Contrato: ninguna intención puede quedar sin entrada en el mapa."""
        for intencion in INTENTS:
            self.assertIn(
                intencion, INTENT_TO_BUTTON,
                'La intención %r no tiene ruta en INTENT_TO_BUTTON' % intencion)

    def test_ninguna_intencion_deja_al_paciente_sin_respuesta(self):
        """Toda intención debe producir texto o botones. Nunca silencio."""
        for intencion in INTENTS:
            if intencion == 'desconocido':
                continue
            s = self._sesion()
            with self._con_intencion(intencion):
                res = self._decir(s, 'texto libre cualquiera',
                                  'W_ALL_%s' % intencion)
            self.assertTrue(
                (res.get('response_text') or '').strip()
                or res.get('meta_payload'),
                'La intención %r dejó al paciente sin respuesta' % intencion)


class TestFallbackSeguro(IntentCase):
    """Sin decisión o con fallo del proveedor: menú, nunca silencio ni LLM."""

    def test_sin_decision_muestra_menu(self):
        s = self._sesion()
        with self._con_intencion(None):
            res = self._decir(s, 'mmm no sé qué escribir', 'W_FB_1')
        self.assertEqual(res.get('fast_path'), 'menu_main')
        self.assertNotEqual(res.get('error'), 'no_active_provider')

    def test_excepcion_del_clasificador_no_rompe(self):
        def _boom(self_, text, session=None):
            raise RuntimeError('proveedor caído')
        s = self._sesion()
        with patch.object(type(self.Clasificador), 'classify', _boom):
            # classify() atrapa todo internamente; acá probamos que aunque
            # se rompa el propio método, la conversación no muere.
            try:
                res = self._decir(s, 'hola qué tal todo', 'W_FB_2')
            except RuntimeError:
                self.fail('Un fallo del clasificador tumbó la conversación')
        self.assertTrue(res)

    def test_kill_switch_desactiva_el_ruteo(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_wa.intent_routing_enabled', 'False')
        s = self._sesion()
        with self._con_intencion('consulta_citas'):
            res = self._decir(s, 'quiero ver mis citas pero raro', 'W_FB_3')
        self.assertIsNone(res.get('intent'),
                          'Con el kill switch en False no debe rutear')


class TestInvarianteLLMNoRedacta(IntentCase):
    """El LLM elige ruta; el texto lo produce el funnel determinista."""

    def test_el_texto_no_viene_del_clasificador(self):
        s = self._sesion()
        with self._con_intencion('consulta_citas'):
            res = self._decir(s, 'texto libre', 'W_INV_1')
        # La respuesta es idéntica a tocar el botón del menú.
        s2 = self._sesion()
        esperado = self.Agent.process_message(
            s2, 'menu:info', wamid='W_INV_2')
        self.assertEqual(res.get('response_text'),
                         esperado.get('response_text'),
                         'La respuesta debe ser la MISMA que la del botón: '
                         'el LLM no redacta, solo enruta.')


class TestKeywordsSiguenTeniendoPrioridad(IntentCase):
    """Las keywords inequívocas no deben gastar una llamada al LLM."""

    def test_keyword_no_invoca_al_clasificador(self):
        llamadas = []

        def _spy(self_, text, session=None):
            llamadas.append(text)
            return None

        s = self._sesion()
        with patch.object(type(self.Clasificador), 'classify', _spy):
            self._decir(s, 'mis citas', 'W_KW_1')
        self.assertFalse(
            llamadas,
            'Una keyword inequívoca no debe llamar al clasificador '
            '(latencia y costo innecesarios)')
