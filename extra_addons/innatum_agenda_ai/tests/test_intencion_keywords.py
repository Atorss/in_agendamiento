# -*- coding: utf-8 -*-
"""Intención en texto libre: verbo + sustantivo NO puede secuestrar 'info'.

Regresión real de producción (2026-07-20): tras agendar por el Flow, el
paciente escribió "Mejor quiero información de mis citas" y el agente volvió
a ofrecerle el Flow de agendar, tres veces seguidas. Causa: la regla genérica
verbo+sustantivo se evaluaba ANTES que las específicas, así que cualquier
frase con "quiero" + "cita" caía en 'agendar'.
"""
from .common_wa_fase2 import Fase2Case


class TestIntencionKeywords(Fase2Case):

    def _kw(self, texto):
        return self.env['innatum.whatsapp.agent']._match_menu_keyword(texto)

    # --- las frases EXACTAS de la conversación de producción ---

    def test_quiero_reservar_otra_consulta(self):
        self.assertEqual(self._kw('Quiero reservar otra consulta'), 'agendar')

    def test_mejor_quiero_informacion_de_mis_citas(self):
        self.assertEqual(
            self._kw('Mejor quiero información de mis citas'), 'info')

    def test_quiero_informacion_de_mis_citas(self):
        self.assertEqual(self._kw('Quiero información de mis citas'), 'info')

    def test_quiero_ver_mis_citas(self):
        self.assertEqual(self._kw('Quiero ver mis citas'), 'info')

    # --- no romper lo que ya funcionaba ---

    def test_agendar_sigue_siendo_agendar(self):
        # Solo frases INEQUÍVOCAS: las keywords quedaron de alta precisión.
        for t in ('quiero agendar una cita', 'agendar',
                  'quiero reservar', 'nueva cita'):
            self.assertEqual(self._kw(t), 'agendar', 'falló: %s' % t)

    def test_frases_ambiguas_las_resuelve_el_clasificador(self):
        # Antes las atrapaba una regla difusa verbo+sustantivo que rompía
        # 'info' (regresión de producción). Ahora devuelven None a propósito:
        # su ruteo es responsabilidad de innatum.wa.intent.classifier.
        for t in ('necesito un turno', 'quiero sacar una cita porfa'):
            self.assertIsNone(self._kw(t), 'no debería matchear keyword: %s' % t)

    def test_info_sin_verbo(self):
        for t in ('mis citas', 'info', 'mi turno', 'mis turnos'):
            self.assertEqual(self._kw(t), 'info', 'falló: %s' % t)

    def test_cancelar_y_reagendar_tienen_prioridad(self):
        self.assertEqual(self._kw('quiero cancelar mi cita'), 'cancelar')
        self.assertEqual(self._kw('quiero reagendar mi cita'), 'reagendar')
        self.assertEqual(self._kw('necesito cambiar fecha de mi turno'),
                         'reagendar')


class TestIntencionEnConversacion(Fase2Case):
    """El mismo caso, pero de punta a punta desde el estado 'confirmada'
    (el estado real en que estaba la sesión tras agendar por el Flow)."""

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.publicar_web = True
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]

    def test_tras_agendar_pedir_info_no_reofrece_agendar(self):
        session = self.Session.create({
            'company_id': self.company.id, 'wa_from': '593990090009',
            'partner_id': self.paciente.id,
        })
        session.action_set_state('confirmada')
        res = self.env['innatum.whatsapp.agent'].process_message(
            session, 'Mejor quiero información de mis citas',
            wamid='W_INTENT_1')
        texto = res.get('response_text') or ''
        self.assertNotIn(
            'Agenda tu cita', texto,
            'Pidió información de sus citas y el agente le reofreció agendar.')
        self.assertNotEqual(res.get('fast_path'), 'flow_agendar')
