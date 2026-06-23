# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AIDataDictionary(models.Model):
    _name = 'innatum.ai.data.dict'
    _description = 'Diccionario de datos para IA'
    _order = 'sequence, id'

    name = fields.Char('Alias / Nombre común', required=True, help='Nombre que el usuario usaría (ej: paciente, empleado, factura)')
    model_name = fields.Char('Modelo técnico', required=True, help='Nombre técnico del modelo Odoo (ej: res.partner)')
    description = fields.Char('Descripción corta')
    key_fields = fields.Text(
        'Campos principales',
        help='Campos más importantes separados por línea: nombre_campo:tipo:descripción',
    )
    sequence = fields.Integer('Secuencia', default=10)
    active = fields.Boolean('Activo', default=True)

    @api.model
    def generate_dict_for_model(self, model_name):
        """Genera automáticamente la entrada del diccionario para un modelo."""
        if model_name not in self.env:
            return False

        Model = self.env[model_name]
        # Get the most useful fields (skip internal/computed ones)
        skip_fields = {
            'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
            '__last_update', 'display_name', 'access_url', 'access_token',
            'access_warning', 'activity_ids', 'activity_state',
            'activity_user_id', 'activity_type_id', 'activity_date_deadline',
            'activity_summary', 'activity_exception_decoration',
            'activity_exception_icon', 'message_ids', 'message_follower_ids',
            'message_partner_ids', 'message_channel_ids', 'message_attachment_count',
            'message_has_error', 'message_has_error_counter', 'message_is_follower',
            'message_main_attachment_id', 'message_needaction', 'message_needaction_counter',
            'message_unread', 'message_unread_counter', 'website_message_ids',
            'has_message', 'rating_ids',
        }

        key_fields_lines = []
        for fname, field in sorted(Model._fields.items()):
            if fname in skip_fields or fname.startswith('__'):
                continue
            if field.type in ('binary', 'reference'):
                continue
            # Include selection values for selection fields
            extra = ''
            if field.type == 'selection' and isinstance(field.selection, list):
                vals = [s[0] for s in field.selection]
                extra = f' [{",".join(str(v) for v in vals)}]'
            key_fields_lines.append(f'{fname}:{field.type}:{field.string}{extra}')

        return {
            'name': Model._description or model_name.split('.')[-1],
            'model_name': model_name,
            'description': Model._description,
            'key_fields': '\n'.join(key_fields_lines[:40]),  # Limit to 40 most important
        }

    @api.model
    def auto_generate_all(self):
        """Genera diccionario para todos los modelos custom instalados."""
        self.env.cr.execute("""
            SELECT model FROM ir_model
            WHERE model LIKE 'innatum.%%' OR model LIKE 'in_%%' OR model LIKE 'th_%%' OR model LIKE 'x_%%'
            ORDER BY model
        """)
        models_list = [r[0] for r in self.env.cr.fetchall()]

        created = 0
        for model_name in models_list:
            if model_name not in self.env:
                continue
            existing = self.search([('model_name', '=', model_name)], limit=1)
            if existing:
                continue
            data = self.generate_dict_for_model(model_name)
            if data:
                self.create(data)
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Diccionario generado',
                'message': f'Se crearon {created} entradas de diccionario.',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def get_context_for_ai(self):
        """Retorna el diccionario compacto: solo alias → modelo + descripción.
        Los campos se consultan bajo demanda con list_model_fields."""
        entries = self.search([('active', '=', True)])
        if not entries:
            return ''

        lines = ['DICCIONARIO DE DATOS (alias → modelo técnico):']
        for entry in entries:
            desc = f' - {entry.description}' if entry.description else ''
            lines.append(f'  {entry.name} → {entry.model_name}{desc}')

        return '\n'.join(lines)
