# -*- coding: utf-8 -*-
"""GOLDEN SET: precisión real del clasificador de intención.

NO corre en la suite normal: necesita un proveedor LLM configurado y gasta
tokens. Se ejecuta a demanda con:

    --test-tags /innatum_agenda_ai:TestIntentGolden

Para qué sirve: el banco determinista (`test_intent_routing.py`) prueba que
CADA intención se rutea bien, pero con el clasificador stubeado. Es decir,
mide el cableado, no el acierto. Este archivo mide el acierto contra frases
reales.

Cómo se mantiene: **cada misruteo observado en producción se agrega acá como
una fila**. Eso es lo que convierte el problema de "parchar una lista de
substrings" en "subir una métrica de cobertura".
"""
import logging

from odoo.tests import tagged

from .common_wa_fase2 import Fase2Case

_logger = logging.getLogger(__name__)

# (texto del paciente, intención esperada)
# Las marcadas [PROD] salieron de conversaciones reales.
GOLDEN = [
    # --- agendar ---
    ('quiero agendar una cita', 'agenda_cita'),
    ('necesito un turno', 'agenda_cita'),
    ('quiero sacar una cita porfa', 'agenda_cita'),
    ('Quiero reservar otra consulta', 'agenda_cita'),            # [PROD]
    ('me pueden dar un espacio para el jueves', 'agenda_cita'),
    ('hola necesito ver al doctor', 'agenda_cita'),
    ('quiero una limpieza dental', 'agenda_cita'),

    # --- consultar citas (el caso que falló en producción) ---
    ('Mejor quiero información de mis citas', 'consulta_citas'),  # [PROD]
    ('Quiero información de mis citas', 'consulta_citas'),        # [PROD]
    ('Quiero ver mis citas', 'consulta_citas'),                   # [PROD]
    ('a qué hora era mi cita', 'consulta_citas'),
    ('cuándo tengo que ir', 'consulta_citas'),
    ('tengo alguna cita pendiente?', 'consulta_citas'),

    # --- cancelar ---
    ('quiero cancelar mi cita', 'cancela_cita'),
    ('ya no voy a poder ir', 'cancela_cita'),
    ('anular la cita del viernes', 'cancela_cita'),

    # --- reagendar ---
    ('necesito cambiar la fecha de mi cita', 'reagenda_cita'),
    ('se me cruzó algo, puedo moverla?', 'reagenda_cita'),
    ('quiero pasar mi cita para otro día', 'reagenda_cita'),

    # --- informativas ---
    ('cuánto cuesta una limpieza', 'info_precios'),
    ('qué precio tiene la ortodoncia', 'info_precios'),
    ('dónde quedan?', 'info_ubicacion'),
    ('cuál es la dirección', 'info_ubicacion'),
    ('atienden los sábados?', 'info_horarios'),
    ('en qué horario atienden', 'info_horarios'),
    ('qué tratamientos hacen', 'info_servicios'),

    # --- sociales ---
    ('hola', 'saludo'),
    ('buenas tardes', 'saludo'),
    ('gracias', 'cortesia'),
    ('ok', 'cortesia'),
    ('quiero hablar con una persona', 'hablar_con_humano'),
    ('me pueden comunicar con la doctora', 'hablar_con_humano'),
]

# Umbral de aceptación. Por debajo, el clasificador necesita ajuste de prompt
# antes de confiar en él en producción.
MIN_ACIERTO = 0.90


@tagged('-standard', 'intent_golden')
class TestIntentGolden(Fase2Case):
    """Requiere proveedor LLM activo. Excluido de la suite estándar."""

    def test_precision_del_clasificador(self):
        Clasificador = self.env['innatum.wa.intent.classifier']
        provider = self.env['innatum.whatsapp.agent']._get_active_provider()
        if not provider:
            self.skipTest('Sin proveedor LLM activo: golden set omitido.')

        session = self.Session.create({
            'company_id': self.company.id, 'wa_from': '593990100010',
            'partner_id': self.paciente.id,
        })
        session.action_set_state('menu_principal')

        aciertos, fallos = 0, []
        for texto, esperada in GOLDEN:
            res = Clasificador.classify(texto, session=session)
            obtenida = (res or {}).get('intention')
            if obtenida == esperada:
                aciertos += 1
            else:
                fallos.append((texto, esperada, obtenida))

        total = len(GOLDEN)
        ratio = aciertos / total if total else 0.0
        _logger.info('')
        _logger.info('===== GOLDEN SET: %d/%d = %.1f%% =====',
                     aciertos, total, ratio * 100)
        for texto, esperada, obtenida in fallos:
            _logger.info('  ✗ %-45s esperado=%-16s obtenido=%s',
                         texto[:45], esperada, obtenida)
        _logger.info('')

        self.assertGreaterEqual(
            ratio, MIN_ACIERTO,
            'Precisión %.1f%% por debajo del mínimo %.0f%%. Fallos: %s'
            % (ratio * 100, MIN_ACIERTO * 100, fallos))
