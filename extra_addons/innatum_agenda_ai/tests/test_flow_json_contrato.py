# -*- coding: utf-8 -*-
"""El Flow JSON es contrato con wa_flow_agent: si el agente puede devolver
una pantalla que el routing_model no declara, Meta expulsa al usuario con
un error genérico en runtime. Este test fija el contrato."""
import json
import pathlib

from odoo.tests.common import TransactionCase

FLOW_JSON = pathlib.Path(__file__).resolve().parents[2] \
    / 'documentacion' / 'flows' / 'FLOW_AGENDAMIENTO.json'

# Derivado de los return de wa_flow_agent.py (handle + _init/_screen_fecha/
# _screen_hora/_post_hora/_identidad/_reservar/_handle_back) + ERROR_SESION
# que el controller/handle() devuelven desde cualquier pantalla ante token/
# sesión inválidos o excepción no controlada.
#
# BACK(screen=X) re-renderiza la pantalla X usando el mismo builder que la
# produce por primera vez (_handle_back), así que las transiciones posibles
# de X también incluyen las de ese builder:
#   BACK a FECHA  -> _screen_fecha() -> mismo builder que SERVICIO -> ya
#                    cubierto por el set de SERVICIO.
#   BACK a HORA   -> _screen_hora()  -> mismo builder que FECHA -> agrega
#                    HORA/FECHA/SERVICIO al set de HORA (antes solo tenía
#                    las transiciones de _post_hora).
#   BACK a SERVICIO -> _init() -> ya cubierto por el propio set de SERVICIO.
#   BACK a IDENTIDAD/CONFIRMAR -> _post_hora() -> agrega CONFIRMAR
#                    (self-loop) al set de CONFIRMAR; IDENTIDAD ya estaba.
TRANSICIONES = {
    # SERVICIO -> _screen_fecha(servicio_code):
    #   servicio no resuelto -> _init(): sin servicios -> ERROR_SESION;
    #   un solo servicio -> _screen_fecha() de nuevo -> FECHA;
    #   varios servicios -> SERVICIO (self-loop).
    #   servicio resuelto -> FECHA.
    'SERVICIO': {'SERVICIO', 'FECHA', 'ERROR_SESION'},
    # FECHA -> _screen_hora(data):
    #   servicio/fecha inválidos (eco roto) -> _init() -> SERVICIO/FECHA/
    #   ERROR_SESION (igual que arriba);
    #   sin slots ese día -> _screen_fecha() -> FECHA (self-loop, día
    #   agotado);
    #   con slots -> HORA.
    'FECHA': {'FECHA', 'HORA', 'SERVICIO', 'ERROR_SESION'},
    # HORA -> _post_hora(data): con partner -> CONFIRMAR; sin partner ->
    # IDENTIDAD.
    # HORA -> (BACK) _screen_hora(data): con slots -> HORA (self-loop,
    # refresh_on_back); sin slots ese día o eco roto -> _screen_fecha()/
    # _init() -> FECHA/SERVICIO/ERROR_SESION.
    'HORA': {'IDENTIDAD', 'CONFIRMAR', 'HORA', 'FECHA', 'SERVICIO',
             'ERROR_SESION'},
    # IDENTIDAD -> _identidad(data): cédula/nombre inválidos -> IDENTIDAD
    # (self-loop); válidos -> _post_hora() -> CONFIRMAR (partner recién
    # vinculado a la sesión).
    'IDENTIDAD': {'IDENTIDAD', 'CONFIRMAR', 'ERROR_SESION'},
    # CONFIRMAR -> _reservar(data, flow_token):
    #   sin partner_id -> _post_hora() -> IDENTIDAD;
    #   slot_id malformado o prof_id ajeno/no-operador -> _init()/
    #   _screen_hora() -> SERVICIO/FECHA/ERROR_SESION/HORA;
    #   hueco robado/inválido -> _screen_hora() -> HORA (quedan cupos ese
    #   día) o FECHA (día agotado tras el robo, fallback interno de
    #   _screen_hora);
    #   éxito -> SUCCESS, pantalla implícita reservada por Meta, ausente
    #   de screens/routing_model a propósito.
    # CONFIRMAR -> (BACK) _post_hora(data): con partner -> CONFIRMAR
    #   (self-loop); sin partner -> IDENTIDAD (ya cubierto).
    'CONFIRMAR': {'HORA', 'FECHA', 'SERVICIO', 'IDENTIDAD', 'CONFIRMAR',
                  'ERROR_SESION'},
    'ERROR_SESION': set(),
}


class TestFlowJsonContrato(TransactionCase):

    def setUp(self):
        super().setUp()
        self.flow = json.loads(FLOW_JSON.read_text())

    def test_routing_model_cubre_las_transiciones_del_agente(self):
        rm = self.flow['routing_model']
        for pantalla, destinos in TRANSICIONES.items():
            declarados = set(rm.get(pantalla, []))
            faltantes = destinos - declarados
            self.assertFalse(
                faltantes,
                'routing_model[%s] no declara %s' % (pantalla, faltantes))

    def test_pantallas_del_json_y_del_agente_coinciden(self):
        ids = {s['id'] for s in self.flow['screens']}
        self.assertEqual(ids, set(TRANSICIONES.keys()))
