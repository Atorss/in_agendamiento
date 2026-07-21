# -*- coding: utf-8 -*-
"""Clasificador de intención para texto libre del paciente (Fase 1).

CONTRATO CENTRAL: el LLM **elige una ruta, nunca redacta**. Devuelve una
intención de una lista CERRADA; la respuesta que lee el paciente la sigue
generando el handler determinista de siempre. Así el LLM pasa de redactor a
traductor: convierte lenguaje natural al vocabulario de botones que el
sistema ya sabe atender.

Por qué existe: el matcher de keywords es una lista de substrings, y cada
frase nueva era un parche. Falló en producción con "quiero información de mis
citas" (verbo + sustantivo lo mandaba a 'agendar'). Este modelo reemplaza esa
adivinanza por una clasificación acotada y medible.

Diseño defensivo: CUALQUIER fallo (sin proveedor, timeout, respuesta
inesperada, excepción) devuelve None. El llamador entonces muestra el menú
principal — nunca silencio, nunca una respuesta inventada.
"""
import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Lista CERRADA de intenciones. Ampliarla es una decisión de producto:
# cada entrada nueva necesita su ruta en INTENT_TO_BUTTON y su caso en el
# golden set.
INTENTS = (
    'agenda_cita',
    'consulta_citas',
    'cancela_cita',
    'reagenda_cita',
    'info_precios',
    'info_ubicacion',
    'info_horarios',
    'info_servicios',
    'saludo',
    'cortesia',
    'hablar_con_humano',
    'desconocido',
)

# Intención → id de botón existente. El clasificador NO inventa rutas: solo
# puede aterrizar en algo que el funnel determinista ya sabe atender.
# `None` = la maneja el llamador con una respuesta propia (no hay botón).
INTENT_TO_BUTTON = {
    'agenda_cita': 'menu:agendar',
    'consulta_citas': 'menu:info',
    'cancela_cita': 'menu:cancelar',
    'reagenda_cita': 'menu:reagendar',
    'info_servicios': 'menu:agendar',   # ver servicios = entrar al funnel
    'info_precios': None,
    'info_ubicacion': None,
    'info_horarios': None,
    'saludo': None,
    'cortesia': None,
    'hablar_con_humano': None,
    'desconocido': None,
}

_SYSTEM = """Eres un clasificador de intenciones para el WhatsApp de un \
consultorio médico/dental. Tu ÚNICA tarea es identificar qué quiere el \
paciente y llamar a la herramienta `clasificar_intencion`.

NUNCA respondes al paciente. NUNCA redactas texto. Solo clasificas.

Intenciones disponibles:
- agenda_cita: quiere reservar/agendar una cita nueva
- consulta_citas: quiere VER o consultar sus citas ya agendadas
- cancela_cita: quiere anular una cita existente
- reagenda_cita: quiere cambiar la fecha/hora de una cita existente
- info_precios: pregunta cuánto cuesta algo
- info_ubicacion: pregunta dónde queda el consultorio
- info_horarios: pregunta en qué horarios o días atienden
- info_servicios: pregunta qué servicios o tratamientos ofrecen
- saludo: solo saluda
- cortesia: agradece, se despide o confirma sin pedir nada ("ok", "gracias")
- hablar_con_humano: pide hablar con una persona real
- desconocido: no encaja claramente en ninguna de las anteriores

REGLAS CRÍTICAS:
1. "quiero/necesito ver mis citas" es consulta_citas, NO agenda_cita. Que la \
frase contenga "cita" no la hace un pedido de agendar.
2. Ante duda real entre dos intenciones, responde `desconocido` con \
confianza baja. Es preferible mostrar el menú a enrutar mal.
3. Usa el estado de la conversación como contexto cuando se te dé."""

_TOOL_SCHEMA = [{
    'name': 'clasificar_intencion',
    'description': 'Registra la intención detectada del paciente.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'intention': {
                'type': 'string',
                'enum': list(INTENTS),
                'description': 'La intención detectada.',
            },
            'confidence': {
                'type': 'number',
                'description': 'Confianza de 0.0 a 1.0.',
            },
        },
        'required': ['intention', 'confidence'],
    },
}]

# Debajo de este umbral se trata como desconocido → menú principal.
MIN_CONFIDENCE = 0.6


class WaIntentClassifier(models.AbstractModel):
    _name = 'innatum.wa.intent.classifier'
    _description = 'Clasificador de intención (texto libre WhatsApp)'

    @api.model
    def classify(self, text, session=None):
        """Clasifica texto libre. Devuelve dict o None.

        Returns:
          {'intention': str, 'confidence': float} si clasificó con confianza
          suficiente, o None en cualquier otro caso (incluidos todos los
          fallos). None significa "no sé": el llamador muestra el menú.
        """
        text = (text or '').strip()
        if not text or len(text) > 300:
            return None
        try:
            return self._classify_llm(text, session)
        except Exception:
            # Nunca propagar: una caída del proveedor no puede tumbar la
            # conversación. El llamador degrada a menú principal.
            _logger.exception(
                'Clasificador de intención falló; se degrada a menú '
                '(session=%s)', session.id if session else None)
            return None

    # ------------------------------------------------------------------

    def _classify_llm(self, text, session):
        provider = self._get_provider()
        if not provider:
            _logger.info('Clasificador: sin proveedor activo')
            return None

        Engine = self.env['innatum.ai.engine']
        caller = Engine._get_api_caller(provider)
        user_msg = text
        if session and session.state:
            # El estado desambigua: "sí" en confirmando_paciente no significa
            # lo mismo que en menu_principal.
            user_msg = ('[estado de la conversación: %s]\n%s'
                        % (session.state, text))

        response = caller(
            provider, [{'role': 'user', 'content': user_msg}],
            tools=_TOOL_SCHEMA, system=_SYSTEM,
        )
        result = self._extract_tool_result(response)
        if not result:
            _logger.info('Clasificador: el modelo no llamó a la herramienta '
                         '(texto=%r)', text[:60])
            return None

        intention = result.get('intention')
        try:
            confidence = float(result.get('confidence') or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        if intention not in INTENTS:
            _logger.info('Clasificador: intención fuera del enum: %r',
                         intention)
            return None
        if intention == 'desconocido' or confidence < MIN_CONFIDENCE:
            _logger.info(
                'Clasificador: sin decisión (intención=%s conf=%.2f) '
                'texto=%r', intention, confidence, text[:60])
            return None

        _logger.info('Clasificador: %r → %s (conf=%.2f)',
                     text[:60], intention, confidence)
        return {'intention': intention, 'confidence': confidence}

    def _get_provider(self):
        """Proveedor para clasificar.

        Se puede apuntar a uno dedicado (modelo chico y rápido: la tarea son
        ~200 tokens de entrada y ~20 de salida, no hace falta el
        conversacional) con el parámetro `innatum_wa.intent_provider_id`.
        Si no está configurado, usa el activo.
        """
        icp = self.env['ir.config_parameter'].sudo()
        pid = icp.get_param('innatum_wa.intent_provider_id')
        if pid:
            provider = self.env['innatum.ai.provider'].sudo().browse(
                int(pid)).exists()
            if provider and provider.active:
                return provider
        return self.env['innatum.whatsapp.agent']._get_active_provider()

    def _extract_tool_result(self, response):
        """Saca el input del tool_use de la respuesta (formato Anthropic;
        el motor ya normaliza los otros proveedores a esta forma)."""
        for block in (response.get('content') or []):
            if block.get('type') == 'tool_use' and block.get('input'):
                return block['input']
        # Algunos proveedores devuelven el JSON como texto plano.
        for block in (response.get('content') or []):
            if block.get('type') == 'text':
                raw = (block.get('text') or '').strip()
                if raw.startswith('{'):
                    try:
                        return json.loads(raw)
                    except ValueError:
                        return None
        return None
