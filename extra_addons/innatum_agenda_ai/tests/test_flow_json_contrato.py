# -*- coding: utf-8 -*-
"""El Flow JSON es contrato con wa_flow_agent Y con el validador de Meta.

Dos familias de invariantes:

1. Semántica de Meta (developers.facebook.com/docs/whatsapp/flows):
   - Existe EXACTAMENTE una pantalla de entrada = la única sin aristas
     entrantes. En nuestro Flow es SERVICIO.
   - Ninguna arista es un self-loop ("Route cannot be the current screen").
     Re-mostrar la misma pantalla con un error es un *refresh*, no una
     transición: NO se declara.
   El BACK lo maneja Meta nativamente: tampoco se declara.

2. Cobertura del agente: toda pantalla DISTINTA que el endpoint pueda
   devolver por `data_exchange` debe estar declarada, o Meta expulsa al
   usuario en runtime. SUCCESS es implícita (reservada por Meta) y el
   self-refresh de validación no cuenta como transición.
"""
import json
import pathlib

from odoo.tests.common import TransactionCase

FLOW_JSON = pathlib.Path(__file__).resolve().parents[2] \
    / 'documentacion' / 'flows' / 'FLOW_AGENDAMIENTO.json'

ENTRADA = 'SERVICIO'

# Transiciones "hacia adelante" del agente: pantallas DISTINTAS que cada
# data_exchange puede devolver (excluye self-refresh de validación, BACK y
# la pantalla implícita SUCCESS). Derivado de wa_flow_agent.handle:
#   SERVICIO  -> _screen_fecha: servicio válido -> FECHA;
#                servicio no resuelto (eco roto) -> _error_sesion.
#   FECHA     -> _screen_hora: con slots -> HORA; eco roto -> _error_sesion.
#                (día agotado -> _screen_fecha -> FECHA = self-refresh, no
#                se declara.)
#   HORA      -> _post_hora: con/sin partner -> CONFIRMAR / IDENTIDAD;
#                excepción -> _error_sesion.
#   IDENTIDAD -> _identidad: válido -> CONFIRMAR; inválido -> IDENTIDAD
#                (self-refresh, no se declara); excepción -> _error_sesion.
#   CONFIRMAR -> _reservar: hueco robado / prof no-operador -> CONFIRMAR
#                (self-refresh con aviso, NO se declara: Meta solo admite
#                rutas hacia adelante y CONFIRMAR->HORA/IDENTIDAD sería
#                backward); sin partner o slot_id malformado -> ERROR_SESION;
#                éxito -> SUCCESS (implícita).
TRANSICIONES = {
    'SERVICIO': {'FECHA', 'ERROR_SESION'},
    'FECHA': {'HORA', 'ERROR_SESION'},
    'HORA': {'IDENTIDAD', 'CONFIRMAR', 'ERROR_SESION'},
    'IDENTIDAD': {'CONFIRMAR', 'ERROR_SESION'},
    'CONFIRMAR': {'ERROR_SESION'},
    'ERROR_SESION': set(),
}


class TestFlowJsonContrato(TransactionCase):

    def setUp(self):
        super().setUp()
        self.flow = json.loads(FLOW_JSON.read_text())
        self.rm = self.flow['routing_model']

    def test_routing_model_cubre_las_transiciones_del_agente(self):
        for pantalla, destinos in TRANSICIONES.items():
            declarados = set(self.rm.get(pantalla, []))
            faltantes = destinos - declarados
            self.assertFalse(
                faltantes,
                'routing_model[%s] no declara %s' % (pantalla, faltantes))

    def test_pantallas_del_json_y_del_agente_coinciden(self):
        ids = {s['id'] for s in self.flow['screens']}
        self.assertEqual(ids, set(TRANSICIONES.keys()))

    def test_sin_self_loops(self):
        """Meta prohíbe que una pantalla se enrute a sí misma."""
        for pantalla, destinos in self.rm.items():
            self.assertNotIn(
                pantalla, destinos,
                'routing_model[%s] contiene un self-loop' % pantalla)

    def test_una_sola_pantalla_de_entrada_sin_aristas_entrantes(self):
        """Meta exige exactamente una pantalla sin aristas entrantes (la de
        entrada). Este invariante habría atrapado las back-edges hacia
        SERVICIO que rompían el import en el Builder."""
        pantallas = set(self.rm.keys())
        con_entrante = set()
        for destinos in self.rm.values():
            con_entrante.update(destinos)
        sin_entrante = pantallas - con_entrante
        self.assertEqual(
            sin_entrante, {ENTRADA},
            'Meta espera exactamente una entrada sin aristas entrantes; '
            'obtenidas: %s' % sin_entrante)

    def test_sin_rutas_backward_directas(self):
        """Meta solo admite rutas hacia adelante: si A->B está declarada,
        B->A NO puede estarlo ('Only forward routes can be specified').
        Este invariante habría atrapado CONFIRMAR->HORA / ->IDENTIDAD."""
        for origen, destinos in self.rm.items():
            for destino in destinos:
                self.assertNotIn(
                    origen, self.rm.get(destino, []),
                    'ruta backward: %s->%s existe con %s->%s declarada'
                    % (destino, origen, origen, destino))

    def test_max_10_ramas_por_pantalla(self):
        """Límite documentado de Meta: máx. 10 ramas por pantalla."""
        for pantalla, destinos in self.rm.items():
            self.assertLessEqual(len(destinos), 10, pantalla)
