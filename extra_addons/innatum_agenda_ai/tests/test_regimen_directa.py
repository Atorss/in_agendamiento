# -*- coding: utf-8 -*-
"""summarize_schedule en modo directa (bug: única primitiva sin rama
directa — devolvía bloques/fechas vacíos y el agente quedaba mudo al
elegir un servicio)."""
from .common_wa_fase2 import Fase2Case


class TestRegimenServicioDirecta(Fase2Case):

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.Primitives = self.env['innatum.agenda.scheduling.primitives']

    def _summ(self):
        return self.Primitives.summarize_schedule(
            self.servicio.code, company=self.company)

    def test_trae_proximas_fechas_con_cupo(self):
        res = self._summ()
        proximas = res['proximas_fechas_con_cupo']
        self.assertTrue(proximas, 'En directa debe calcular fechas con '
                                  'cupo desde los huecos libres reales')
        self.assertLessEqual(len(proximas), 5)
        primera = proximas[0]
        self.assertIn('fecha_iso', primera)
        self.assertTrue(primera['fecha_label'])
        self.assertGreater(primera['cupos'], 0)
        self.assertEqual(res['servicio'], 'Endodoncia')

    def test_trae_bloques_del_calendario_laboral(self):
        res = self._summ()
        self.assertTrue(res['bloques'], 'El régimen debe salir del '
                                        'calendario laboral del operador')
        blk = res['bloques'][0]
        self.assertEqual(blk['professional'], 'Dra. Ana')
        self.assertEqual(blk['duracion_turno_min'], 60)
        self.assertTrue(blk['dias'])
        self.assertIn(' - ', blk['horario_text'])

    def test_sin_operadores_no_rompe(self):
        self.servicio.operador_ids = [(5, 0, 0)]
        res = self._summ()
        self.assertEqual(res['proximas_fechas_con_cupo'], [])
        self.assertEqual(res['bloques'], [])

    def test_planificada_sigue_igual(self):
        self.company.agenda_modo = 'planificada'
        res = self._summ()
        # Sin planificaciones aprobadas ni turnos publicados, planificada
        # sigue devolviendo vacío: su comportamiento no cambia.
        self.assertEqual(res['proximas_fechas_con_cupo'], [])
        self.assertEqual(res['bloques'], [])
