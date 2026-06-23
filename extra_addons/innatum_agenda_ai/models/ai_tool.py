# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


class AITool(models.Model):
    _name = 'innatum.ai.tool'
    _description = 'Herramienta de IA'
    _order = 'sequence, id'

    name = fields.Char('Nombre técnico', required=True, help='Nombre usado internamente por la IA')
    display_name_field = fields.Char('Nombre para mostrar', required=True)
    description = fields.Text('Descripción', required=True, help='Descripción que la IA ve para decidir cuándo usar esta herramienta')
    sequence = fields.Integer('Secuencia', default=10)
    active = fields.Boolean('Activo', default=True)

    tool_type = fields.Selection([
        ('search', 'Buscar registros'),
        ('read', 'Leer registros'),
        ('create', 'Crear registro'),
        ('write', 'Modificar registro'),
        ('unlink', 'Eliminar registro'),
        ('method', 'Ejecutar método'),
        ('sql_report', 'Consulta SQL (solo lectura)'),
        ('list_fields', 'Listar campos de modelo'),
    ], string='Tipo', required=True, default='search')

    allowed_models = fields.Char(
        'Modelos permitidos',
        help='Lista separada por comas de modelos permitidos (ej: res.partner,sale.order). Vacío = todos.',
    )

    requires_confirmation = fields.Boolean(
        'Requiere confirmación',
        default=False,
        help='Si está activo, la IA pedirá confirmación antes de ejecutar esta herramienta',
    )

    group_ids = fields.Many2many(
        'res.groups',
        'innatum_ai_tool_group_rel',
        'tool_id', 'group_id',
        string='Grupos permitidos',
        help='Grupos que pueden usar esta herramienta. Vacío = todos.',
    )

    def _get_tool_schema(self):
        """Retorna el schema de la herramienta en formato compatible con tool use."""
        self.ensure_one()
        schemas = {
            'search': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo (ej: res.partner, sale.order)',
                        },
                        'domain': {
                            'type': 'string',
                            'description': 'Dominio de búsqueda en formato JSON (ej: [["name","ilike","juan"]])',
                        },
                        'fields': {
                            'type': 'string',
                            'description': 'Campos a retornar separados por coma (ej: name,email,phone). Vacío = todos.',
                        },
                        'limit': {
                            'type': 'integer',
                            'description': 'Número máximo de registros (default: 20)',
                        },
                        'order': {
                            'type': 'string',
                            'description': 'Orden de resultados (ej: name asc, create_date desc)',
                        },
                    },
                    'required': ['model'],
                },
            },
            'read': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo',
                        },
                        'record_ids': {
                            'type': 'string',
                            'description': 'IDs de registros separados por coma (ej: 1,2,3)',
                        },
                        'fields': {
                            'type': 'string',
                            'description': 'Campos a leer separados por coma',
                        },
                    },
                    'required': ['model', 'record_ids'],
                },
            },
            'create': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo',
                        },
                        'values': {
                            'type': 'string',
                            'description': 'Valores en formato JSON (ej: {"name": "Juan", "email": "j@e.com"})',
                        },
                    },
                    'required': ['model', 'values'],
                },
            },
            'write': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo',
                        },
                        'record_ids': {
                            'type': 'string',
                            'description': 'IDs de registros separados por coma',
                        },
                        'values': {
                            'type': 'string',
                            'description': 'Valores a actualizar en formato JSON',
                        },
                    },
                    'required': ['model', 'record_ids', 'values'],
                },
            },
            'unlink': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo',
                        },
                        'record_ids': {
                            'type': 'string',
                            'description': 'IDs de registros a eliminar separados por coma',
                        },
                    },
                    'required': ['model', 'record_ids'],
                },
            },
            'method': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo',
                        },
                        'method': {
                            'type': 'string',
                            'description': 'Nombre del método a ejecutar',
                        },
                        'record_ids': {
                            'type': 'string',
                            'description': 'IDs de registros (vacío para métodos de modelo)',
                        },
                        'args': {
                            'type': 'string',
                            'description': 'Argumentos en formato JSON',
                        },
                    },
                    'required': ['model', 'method'],
                },
            },
            'sql_report': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'query_description': {
                            'type': 'string',
                            'description': 'Descripción en lenguaje natural de los datos que necesitas',
                        },
                    },
                    'required': ['query_description'],
                },
            },
            'list_fields': {
                'name': self.name,
                'description': self.description,
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'model': {
                            'type': 'string',
                            'description': 'Modelo de Odoo (ej: res.partner, res.partner)',
                        },
                    },
                    'required': ['model'],
                },
            },
        }
        return schemas.get(self.tool_type, schemas['search'])

    def check_tool_access(self, user):
        """Verifica si el usuario tiene acceso a esta herramienta."""
        self.ensure_one()
        if not self.group_ids:
            return True
        return bool(self.group_ids & user.groups_id)

    def _check_model_allowed(self, model_name):
        """Verifica si el modelo está permitido para esta herramienta."""
        self.ensure_one()
        if not self.allowed_models:
            return True
        allowed = [m.strip() for m in self.allowed_models.split(',')]
        return model_name in allowed

    def execute_tool(self, params, user=None):
        """Ejecuta la herramienta con los parámetros dados."""
        self.ensure_one()
        if user and not self.check_tool_access(user):
            raise AccessError(f'No tienes permiso para usar la herramienta: {self.display_name_field}')

        method_map = {
            'search': self._execute_search,
            'read': self._execute_read,
            'create': self._execute_create,
            'write': self._execute_write,
            'unlink': self._execute_unlink,
            'method': self._execute_method,
            'sql_report': self._execute_sql_report,
            'list_fields': self._execute_list_fields,
        }

        executor = method_map.get(self.tool_type)
        if not executor:
            raise UserError(f'Tipo de herramienta no soportado: {self.tool_type}')

        try:
            return executor(params)
        except Exception as e:
            _logger.error('Error ejecutando herramienta %s: %s', self.name, str(e))
            return {'error': str(e)}

    def _validate_model(self, model_name):
        """Valida que el modelo exista y esté permitido."""
        if not self._check_model_allowed(model_name):
            raise UserError(f'Modelo no permitido: {model_name}')
        if model_name not in self.env:
            raise UserError(f'Modelo no encontrado: {model_name}')
        return self.env[model_name]

    def _normalize_domain(self, domain_raw):
        """Normaliza el domain a formato Odoo [[field, op, value], ...]."""
        if not domain_raw:
            return []
        if isinstance(domain_raw, str):
            domain_raw = json.loads(domain_raw)
        if not isinstance(domain_raw, list):
            return []

        domain = []
        for item in domain_raw:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                # Already in correct format: ["field", "=", "value"]
                domain.append(list(item))
            elif isinstance(item, dict):
                # Dict format from OpenAI: {"field": "value"} → convert to Odoo domain
                for field, value in item.items():
                    domain.append([field, '=', value])
            elif isinstance(item, str):
                # Domain operator like '|', '&'
                domain.append(item)
        return domain

    def _execute_search(self, params):
        model_name = params.get('model', '')
        Model = self._validate_model(model_name)

        domain = self._normalize_domain(params.get('domain', '[]'))
        field_names = [f.strip() for f in params.get('fields', '').split(',') if f.strip()]
        limit = int(params.get('limit', 20)) or 20
        order = params.get('order', '')

        if not field_names:
            field_names = ['name', 'display_name']
            # Add common useful fields if they exist
            for fname in ['state', 'create_date', 'active']:
                if fname in Model._fields:
                    field_names.append(fname)

        records = Model.search_read(domain, field_names, limit=limit, order=order or None)

        # Serialize dates and other non-JSON types
        for record in records:
            for key, val in record.items():
                if hasattr(val, 'isoformat'):
                    record[key] = val.isoformat()
                elif isinstance(val, bytes):
                    record[key] = '<binary data>'

        return {
            'model': model_name,
            'count': len(records),
            'total': Model.search_count(domain),
            'records': records,
        }

    def _execute_read(self, params):
        model_name = params.get('model', '')
        Model = self._validate_model(model_name)

        ids = [int(x.strip()) for x in params.get('record_ids', '').split(',') if x.strip()]
        field_names = [f.strip() for f in params.get('fields', '').split(',') if f.strip()]

        records = Model.browse(ids).read(field_names or None)

        for record in records:
            for key, val in record.items():
                if hasattr(val, 'isoformat'):
                    record[key] = val.isoformat()
                elif isinstance(val, bytes):
                    record[key] = '<binary data>'

        return {'model': model_name, 'records': records}

    def _execute_create(self, params):
        model_name = params.get('model', '')
        Model = self._validate_model(model_name)
        values = json.loads(params.get('values', '{}'))
        record = Model.create(values)
        return {
            'model': model_name,
            'id': record.id,
            'display_name': record.display_name,
            'message': f'Registro creado exitosamente: {record.display_name} (ID: {record.id})',
        }

    def _execute_write(self, params):
        model_name = params.get('model', '')
        Model = self._validate_model(model_name)
        ids = [int(x.strip()) for x in params.get('record_ids', '').split(',') if x.strip()]
        values = json.loads(params.get('values', '{}'))
        records = Model.browse(ids)
        records.write(values)
        return {
            'model': model_name,
            'ids': ids,
            'message': f'{len(ids)} registro(s) actualizado(s) exitosamente',
        }

    def _execute_unlink(self, params):
        model_name = params.get('model', '')
        Model = self._validate_model(model_name)
        ids = [int(x.strip()) for x in params.get('record_ids', '').split(',') if x.strip()]
        records = Model.browse(ids)
        count = len(records)
        records.unlink()
        return {
            'model': model_name,
            'message': f'{count} registro(s) eliminado(s) exitosamente',
        }

    def _execute_method(self, params):
        model_name = params.get('model', '')
        Model = self._validate_model(model_name)
        method_name = params.get('method', '')

        # Security: only allow public methods
        if method_name.startswith('_'):
            raise UserError(f'No se permite ejecutar métodos privados: {method_name}')

        if not hasattr(Model, method_name):
            raise UserError(f'Método no encontrado: {model_name}.{method_name}')

        record_ids = params.get('record_ids', '')
        args = json.loads(params.get('args', '[]'))

        if record_ids:
            ids = [int(x.strip()) for x in record_ids.split(',') if x.strip()]
            result = getattr(Model.browse(ids), method_name)(*args)
        else:
            result = getattr(Model, method_name)(*args)

        # Try to serialize the result
        try:
            json.dumps(result)
            return {'result': result}
        except (TypeError, ValueError):
            return {'result': str(result)}

    def _execute_sql_report(self, params):
        """Genera y ejecuta una consulta SQL de solo lectura."""
        query_description = params.get('query_description', '')
        # The AI engine will handle SQL generation via a second AI call
        # Here we just return the description for the engine to process
        return {
            'type': 'sql_report_request',
            'description': query_description,
            'message': 'La consulta SQL será generada y ejecutada por el motor de IA.',
        }

    _SKIP_FIELD_PREFIXES = ('message_', 'activity_', 'website_message_', 'rating_', 'has_message')
    _SKIP_FIELDS = {
        'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
        '__last_update', 'display_name', 'access_url', 'access_token',
        'access_warning',
    }

    def _execute_list_fields(self, params):
        """Lista los campos útiles de un modelo (sin campos internos)."""
        model_name = params.get('model', '')
        if model_name not in self.env:
            raise UserError(f'Modelo no encontrado: {model_name}')

        Model = self.env[model_name]
        fields_info = []
        for fname, field in sorted(Model._fields.items()):
            if fname.startswith('__') or fname in self._SKIP_FIELDS:
                continue
            if any(fname.startswith(p) for p in self._SKIP_FIELD_PREFIXES):
                continue
            if field.type in ('binary',):
                continue
            info = f'{fname}:{field.type}:{field.string}'
            if field.type == 'many2one' and field.comodel_name:
                info += f' -> {field.comodel_name}'
            elif field.type == 'selection' and isinstance(field.selection, list):
                vals = [s[0] for s in field.selection]
                info += f' [{",".join(str(v) for v in vals)}]'
            fields_info.append(info)

        return {
            'model': model_name,
            'description': Model._description,
            'fields': fields_info,
        }
