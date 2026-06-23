# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Modelos disponibles por proveedor
PROVIDER_MODELS = {
    'anthropic': [
        ('claude-haiku-4-5-20251001', 'Claude Haiku 4.5'),
        ('claude-sonnet-4-5-20250514', 'Claude Sonnet 4.5'),
        ('claude-sonnet-4-6', 'Claude Sonnet 4.6'),
        ('claude-opus-4-6', 'Claude Opus 4.6'),
    ],
    'openai': [
        ('gpt-4o-mini', 'GPT-4o Mini'),
        ('gpt-4o', 'GPT-4o'),
        ('gpt-4.1', 'GPT-4.1'),
        ('gpt-4.1-mini', 'GPT-4.1 Mini'),
        ('gpt-4.1-nano', 'GPT-4.1 Nano'),
        ('o3-mini', 'o3 Mini'),
    ],
    'google': [
        ('gemini-2.0-flash', 'Gemini 2.0 Flash'),
        ('gemini-2.5-flash-preview-05-20', 'Gemini 2.5 Flash'),
        ('gemini-2.5-pro-preview-05-06', 'Gemini 2.5 Pro'),
    ],
}

# Lista plana de todos los modelos para el campo Selection
ALL_MODELS = []
for _provider, models_list in PROVIDER_MODELS.items():
    ALL_MODELS.extend(models_list)


# Precios por modelo (USD / 1M tokens) como default sugerido.
# El admin puede sobrescribirlos manualmente en cada provider.
MODEL_PRICING = {
    'claude-haiku-4-5-20251001':       (1.00, 5.00),
    'claude-sonnet-4-5-20250514':      (3.00, 15.00),
    'claude-sonnet-4-6':               (3.00, 15.00),
    'claude-opus-4-6':                 (15.00, 75.00),
    'gpt-4o-mini':                     (0.15, 0.60),
    'gpt-4o':                          (2.50, 10.00),
    'gpt-4.1':                         (2.00, 8.00),
    'gpt-4.1-mini':                    (0.40, 1.60),
    'gpt-4.1-nano':                    (0.10, 0.40),
    'o3-mini':                         (1.10, 4.40),
    'gemini-2.0-flash':                (0.075, 0.30),
    'gemini-2.5-flash-preview-05-20':  (0.30, 2.50),
    'gemini-2.5-pro-preview-05-06':    (1.25, 10.00),
}


class AIProvider(models.Model):
    _name = 'innatum.ai.provider'
    _description = 'Proveedor de IA'
    _order = 'sequence, id'

    name = fields.Char('Nombre', required=True)
    sequence = fields.Integer('Secuencia', default=10)
    active = fields.Boolean('Activo', default=True)

    provider_type = fields.Selection([
        ('anthropic', 'Claude (Anthropic)'),
        ('openai', 'OpenAI (GPT)'),
        ('google', 'Google (Gemini)'),
    ], string='Proveedor', required=True, default='anthropic')

    api_key = fields.Char('API Key', required=True, groups='innatum_agenda_ai.group_ai_admin')
    api_base_url = fields.Char('URL Base API', help='Dejar vacío para usar la URL por defecto del proveedor')

    model_id_name = fields.Selection(
        selection=ALL_MODELS,
        string='Modelo',
        required=True,
        default='claude-haiku-4-5-20251001',
    )

    # Campo para modelos personalizados no listados
    custom_model = fields.Char(
        'Modelo Personalizado',
        help='Si tu modelo no aparece en la lista, escríbelo aquí. Tiene prioridad sobre el selector.',
    )

    max_tokens = fields.Integer('Max Tokens Respuesta', default=4096)
    temperature = fields.Float('Temperatura', default=0.3, digits=(3, 2))

    system_prompt = fields.Text(
        'Prompt del Sistema',
        default=lambda self: self._default_system_prompt(),
    )

    is_default = fields.Boolean('Proveedor por Defecto', default=False)

    # --- Pricing (USD por 1 millón de tokens) ---
    price_1m_input_usd = fields.Float(
        'Precio Input (USD/1M tokens)', digits=(10, 4), default=1.0,
        help='Costo por 1 millón de tokens de entrada. Se precarga al cambiar '
             'de modelo — puedes ajustarlo manualmente si tu tarifa difiere.',
    )
    price_1m_output_usd = fields.Float(
        'Precio Output (USD/1M tokens)', digits=(10, 4), default=5.0,
        help='Costo por 1 millón de tokens de salida. Se precarga al cambiar '
             'de modelo.',
    )

    conversation_ids = fields.One2many('innatum.ai.conversation', 'provider_id', string='Conversaciones')

    @api.model
    def _default_system_prompt(self):
        return (
            "Eres un asistente de IA integrado en el ERP Odoo. "
            "Tu trabajo es ayudar a los usuarios a consultar datos, crear registros, "
            "generar reportes y analizar información del sistema. "
            "Responde siempre en español. Sé conciso y preciso. "
            "Cuando necesites datos del ERP, usa las herramientas disponibles. "
            "Si no estás seguro de algo, pregunta antes de ejecutar acciones destructivas."
        )

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        """Al cambiar proveedor, resetear al primer modelo disponible."""
        if self.provider_type:
            models_for_provider = PROVIDER_MODELS.get(self.provider_type, [])
            if models_for_provider:
                self.model_id_name = models_for_provider[0][0]
            else:
                self.model_id_name = False
            self.custom_model = False

    @api.onchange('model_id_name')
    def _onchange_model_id_name(self):
        """Al cambiar de modelo, precargar precios típicos (override manual posible)."""
        if self.model_id_name and self.model_id_name in MODEL_PRICING:
            price_in, price_out = MODEL_PRICING[self.model_id_name]
            self.price_1m_input_usd = price_in
            self.price_1m_output_usd = price_out

    @property
    def effective_model(self):
        """Retorna el modelo efectivo: custom_model si existe, sino model_id_name."""
        return self.custom_model or self.model_id_name

    @api.constrains('is_default')
    def _check_default_unique(self):
        for record in self:
            if record.is_default:
                existing = self.search([
                    ('is_default', '=', True),
                    ('id', '!=', record.id),
                ])
                if existing:
                    existing.write({'is_default': False})

    @api.model
    def get_default_provider(self):
        """Obtiene el proveedor por defecto o el primero activo."""
        provider = self.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if not provider:
            provider = self.search([('active', '=', True)], limit=1)
        if not provider:
            raise ValidationError('No hay ningún proveedor de IA configurado. Ve a Ajustes > AI Assistant.')
        return provider

    def test_connection(self):
        """Prueba la conexión con el proveedor."""
        self.ensure_one()
        engine = self.env['innatum.ai.engine'].with_context(
            ai_source='test_connection',
            ai_record_ref=f'innatum.ai.provider,{self.id}',
        )
        try:
            response = engine.simple_completion(
                self, "Responde solo con: OK"
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Conexión exitosa',
                    'message': f'Respuesta del modelo: {response[:100]}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except UserError as exc:
            _logger.warning('Test de conexión con %s fallido: %s',
                            self.provider_type, exc)
            return self._notif_connection_error(str(exc))
        except Exception as exc:
            _logger.exception('Error inesperado probando conexión con %s',
                              self.provider_type)
            return self._notif_connection_error(
                'Error inesperado. Revisa los logs del servidor.'
            )

    def _notif_connection_error(self, message):
        """Helper: notification con mensaje saneado (redacta API key)."""
        if self.api_key and len(self.api_key) > 4:
            message = message.replace(self.api_key, '***REDACTED***')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Error de conexión',
                'message': str(message)[:300],
                'type': 'danger',
                'sticky': True,
            },
        }
