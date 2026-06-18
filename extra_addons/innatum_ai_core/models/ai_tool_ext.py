# -*- coding: utf-8 -*-
"""Extensiones a innatum.ai.tool: schema custom + dispatch a método Python.

`innatum_ai` define tools genéricas (search/read/create/method/...). Para el
agente WhatsApp necesitamos tools de dominio (consultar_servicios, reservar_turno,
etc.) con su propio input_schema y un método Python específico por tool.

Estrategia:
- `tool_type` gana un nuevo valor `'wa_agent'` que indica "tool de agente WhatsApp"
- `custom_input_schema` (JSON string) define el schema que ve el LLM
- `python_method_path` ("model:method") apunta al método a invocar
- override `_get_tool_schema()` y `execute_tool()` para usar lo anterior cuando aplica
"""
import json
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AIToolExt(models.Model):
    _inherit = 'innatum.ai.tool'

    tool_type = fields.Selection(
        selection_add=[('wa_agent', 'WhatsApp Agent Tool')],
        ondelete={'wa_agent': 'cascade'},
    )

    custom_input_schema = fields.Text(
        string='Input Schema (JSON)',
        help='JSON Schema del input que verá el LLM. Solo aplica si tool_type=wa_agent.',
    )
    python_method_path = fields.Char(
        string='Método Python',
        help='Formato "<modelo>:<método>". El método recibe (params_dict, session) y '
             'devuelve dict serializable. Solo aplica si tool_type=wa_agent.',
    )

    def _get_tool_schema(self):
        """Para wa_agent devolver el schema custom; resto comportamiento original."""
        self.ensure_one()
        if self.tool_type == 'wa_agent':
            try:
                input_schema = json.loads(self.custom_input_schema or '{}')
            except json.JSONDecodeError:
                _logger.warning(
                    'Tool %s tiene custom_input_schema inválido', self.name)
                input_schema = {'type': 'object', 'properties': {}}
            return {
                'name': self.name,
                'description': self.description or '',
                'input_schema': input_schema,
            }
        return super()._get_tool_schema()

    def execute_tool(self, params, user=None, session=None):
        """Para wa_agent invoca python_method_path con (params, session).

        `session` se pasa via context kwarg ya que el método super no lo espera.
        """
        self.ensure_one()
        if self.tool_type == 'wa_agent':
            if user and not self.check_tool_access(user):
                from odoo.exceptions import AccessError
                raise AccessError(
                    f'Sin acceso a la herramienta: {self.display_name_field}')
            return self._execute_wa_agent(params, session=session)
        return super().execute_tool(params, user=user)

    def _execute_wa_agent(self, params, session=None):
        """Dispatch a python_method_path."""
        self.ensure_one()
        path = (self.python_method_path or '').strip()
        if ':' not in path:
            raise UserError(
                f'Tool {self.name}: python_method_path inválido (formato "model:method")')

        model_name, method_name = path.split(':', 1)
        if model_name not in self.env:
            raise UserError(f'Tool {self.name}: modelo {model_name} no existe')

        Model = self.env[model_name].sudo()
        method = getattr(Model, method_name, None)
        if not callable(method):
            raise UserError(
                f'Tool {self.name}: método {method_name} no existe en {model_name}')

        try:
            with self.env.cr.savepoint():
                return method(params, session=session)
        except UserError:
            raise
        except Exception as exc:
            _logger.exception(
                'Tool %s falló al invocar %s', self.name, path)
            return {'error': str(exc)}
