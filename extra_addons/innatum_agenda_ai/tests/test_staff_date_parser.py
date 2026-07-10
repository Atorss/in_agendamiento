# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo.tests.common import TransactionCase

from ..models.staff_date_parser import parse_fecha_escrita

# mié 15 jul 2026 14:00 UTC = 09:00 en Ecuador (UTC-5).
AHORA = datetime(2026, 7, 15, 14, 0)


class TestStaffDateParser(TransactionCase):
    """Parser determinista: formatos concretos → datetime UTC naive."""

    def p(self, text, dia=None):
        return parse_fecha_escrita(text, AHORA, dia_contexto=dia)

    def test_manana_con_hora(self):
        self.assertEqual(self.p('mañana 15:00'),
                         datetime(2026, 7, 16, 20, 0))

    def test_hoy_pm(self):
        self.assertEqual(self.p('hoy 3pm'), datetime(2026, 7, 15, 20, 0))

    def test_pasado_manana(self):
        self.assertEqual(self.p('pasado mañana 9:30'),
                         datetime(2026, 7, 17, 14, 30))

    def test_dia_semana_futuro(self):
        # 15/07/2026 es miércoles; viernes = 17/07.
        self.assertEqual(self.p('viernes 10am'),
                         datetime(2026, 7, 17, 15, 0))

    def test_dia_semana_siguiente_semana(self):
        self.assertEqual(self.p('lunes 9:00'), datetime(2026, 7, 20, 14, 0))

    def test_mismo_dow_hora_no_pasada_es_hoy(self):
        # Hoy mié 09:00 local; "miércoles 10:00" aún no pasa → hoy.
        self.assertEqual(self.p('miércoles 10:00'),
                         datetime(2026, 7, 15, 15, 0))

    def test_mismo_dow_hora_pasada_rueda_una_semana(self):
        # "miercoles 8:00" ya pasó (son las 09:00) → mié 22/07.
        self.assertEqual(self.p('miercoles 8:00'),
                         datetime(2026, 7, 22, 13, 0))

    def test_fecha_numerica(self):
        for t in ('15/07 10:00', '15/7 10:00', '15-07 10:00',
                  '15/07/2026 10:00', '15/07/26 10:00'):
            self.assertEqual(self.p(t), datetime(2026, 7, 15, 15, 0), t)

    def test_fecha_sin_anio_pasada_rueda_al_siguiente_anio(self):
        # "05/01" en julio 2026 → 05/01/2027 (no enero pasado).
        self.assertEqual(self.p('05/01 10:00'), datetime(2027, 1, 5, 15, 0))

    def test_hora_sola_con_contexto(self):
        self.assertEqual(self.p('3:30pm', dia=date(2026, 7, 20)),
                         datetime(2026, 7, 20, 20, 30))

    def test_formato_hora_con_h(self):
        self.assertEqual(self.p('hoy 09h30'), datetime(2026, 7, 15, 14, 30))

    def test_mediodia_y_medianoche(self):
        self.assertEqual(self.p('hoy 12pm'), datetime(2026, 7, 15, 17, 0))
        self.assertEqual(self.p('mañana 12am'), datetime(2026, 7, 16, 5, 0))

    def test_mayusculas_y_tildes(self):
        self.assertEqual(self.p('MAÑANA 15:00'),
                         datetime(2026, 7, 16, 20, 0))

    def test_rechazos_devuelven_none(self):
        for t in ('3pm',                # hora sola sin día en contexto
                  'hola', '', 'mañana', # sin hora
                  'hoy 15',             # número suelto sin :MM ni am/pm
                  '99/99 10:00',        # fecha inválida
                  'hoy 25:00',          # hora inválida
                  'el lunes que viene tempranito'):
            self.assertIsNone(self.p(t), t)
