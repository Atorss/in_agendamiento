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


class TestFindAvailabilityDirecta(Fase2Case):
    """find_availability en modo directa debe agrupar por período cuando
    hay fecha — es contrato con el renderizador del agente: el embudo
    AM/PM lee total_am/pm/night y la lista de ≤10 lee agrupado_por_periodo.
    Sin ellos, el agente decía 'Hay 16 turnos' sin ningún botón de hora."""

    def setUp(self):
        super().setUp()
        self.company.agenda_modo = 'directa'
        self.servicio.operador_ids = [(6, 0, self.colaboradora.ids)]
        self.Primitives = self.env['innatum.agenda.scheduling.primitives']

    def _fecha_con_cupo(self):
        """Última fecha con cupo (día completo futuro, no el parcial de hoy)."""
        res = self.Primitives.summarize_schedule(
            self.servicio.code, company=self.company)
        return res['proximas_fechas_con_cupo'][-1]['fecha_iso']

    def test_con_fecha_y_muchos_slots_arma_embudo(self):
        self.servicio.duracion = 30.0   # ~16 huecos/día → embudo AM/PM
        fecha = self._fecha_con_cupo()
        res = self.Primitives.find_availability(
            self.servicio.code, fecha=fecha, company=self.company)
        self.assertGreater(res['total_disponibles'], 10)
        self.assertIn('agrupado_por_periodo', res)
        self.assertEqual(
            res['total_am'] + res['total_pm'] + res['total_night'],
            res['total_disponibles'])
        self.assertIn('hint_periodo', res)

    def test_con_fecha_y_pocos_slots_agrupa_sin_hint(self):
        fecha = self._fecha_con_cupo()   # 60 min → ~8 huecos/día
        res = self.Primitives.find_availability(
            self.servicio.code, fecha=fecha, company=self.company)
        self.assertLessEqual(res['total_disponibles'], 10)
        self.assertIn('agrupado_por_periodo', res)
        grouped = res['agrupado_por_periodo']
        self.assertEqual(
            len(grouped['AM']) + len(grouped['PM']) + len(grouped['NIGHT']),
            res['total_disponibles'])
        self.assertNotIn('hint_periodo', res)

    def test_filtro_periodo_am(self):
        fecha = self._fecha_con_cupo()
        res = self.Primitives.find_availability(
            self.servicio.code, fecha=fecha, periodo='AM',
            company=self.company)
        self.assertEqual(res.get('periodo'), 'AM')
        self.assertTrue(res['slots'])
        self.assertTrue(all(s['periodo'] == 'AM' for s in res['slots']))
