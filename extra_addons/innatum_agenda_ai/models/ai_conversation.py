# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api


class AIConversation(models.Model):
    _name = 'innatum.ai.conversation'
    _description = 'Conversación con IA'
    _order = 'create_date desc'

    name = fields.Char('Título', required=True, default='Nueva conversación')
    company_id = fields.Many2one(
        'res.company', string='Empresa', required=True, index=True,
        default=lambda self: self.env.company,
    )
    provider_id = fields.Many2one('innatum.ai.provider', string='Proveedor', required=True, ondelete='restrict')
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user, required=True)
    message_ids = fields.One2many('innatum.ai.message', 'conversation_id', string='Mensajes')
    message_count = fields.Integer('Mensajes', compute='_compute_message_count')
    total_input_tokens = fields.Integer('Tokens entrada', compute='_compute_token_totals', store=True)
    total_output_tokens = fields.Integer('Tokens salida', compute='_compute_token_totals', store=True)
    total_tokens = fields.Integer('Tokens total', compute='_compute_token_totals', store=True)
    total_api_calls = fields.Integer('Llamadas API', compute='_compute_token_totals', store=True)
    total_cost_usd = fields.Float(
        'Costo (USD)', digits=(12, 6),
        compute='_compute_cost_totals', store=True,
    )
    state = fields.Selection([
        ('active', 'Activa'),
        ('archived', 'Archivada'),
    ], string='Estado', default='active')

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    @api.depends('message_ids.input_tokens', 'message_ids.output_tokens')
    def _compute_token_totals(self):
        for rec in self:
            msgs = rec.message_ids
            rec.total_input_tokens = sum(msgs.mapped('input_tokens'))
            rec.total_output_tokens = sum(msgs.mapped('output_tokens'))
            rec.total_tokens = rec.total_input_tokens + rec.total_output_tokens
            rec.total_api_calls = len(msgs.filtered(lambda m: m.input_tokens > 0))

    @api.depends('message_ids.cost_usd')
    def _compute_cost_totals(self):
        for rec in self:
            rec.total_cost_usd = sum(rec.message_ids.mapped('cost_usd'))

    def get_messages_for_api(self):
        """Retorna el historial de mensajes en formato API."""
        self.ensure_one()
        messages = []
        for msg in self.message_ids.sorted('sequence'):
            if msg.role in ('user', 'assistant'):
                messages.append({
                    'role': msg.role,
                    'content': msg.content,
                })
        return messages

    def add_message(self, role, content, tool_calls=None, tool_results=None,
                    input_tokens=0, output_tokens=0):
        """Agrega un mensaje a la conversación con snapshot de costo."""
        self.ensure_one()
        last_seq = max(self.message_ids.mapped('sequence') or [0])
        price_in = self.provider_id.price_1m_input_usd or 0.0
        price_out = self.provider_id.price_1m_output_usd or 0.0
        cost_usd = (
            (input_tokens * price_in + output_tokens * price_out) / 1_000_000
        )
        vals = {
            'conversation_id': self.id,
            'role': role,
            'content': content,
            'sequence': last_seq + 1,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'price_1m_input_snapshot': price_in,
            'price_1m_output_snapshot': price_out,
            'cost_usd': cost_usd,
        }
        if tool_calls:
            vals['tool_calls_json'] = json.dumps(tool_calls)
        if tool_results:
            vals['tool_results_json'] = json.dumps(tool_results)
        return self.env['innatum.ai.message'].create(vals)


class AIMessage(models.Model):
    _name = 'innatum.ai.message'
    _description = 'Mensaje de conversación IA'
    _order = 'sequence, id'

    conversation_id = fields.Many2one('innatum.ai.conversation', string='Conversación', required=True, ondelete='cascade')
    sequence = fields.Integer('Secuencia', default=10)
    role = fields.Selection([
        ('user', 'Usuario'),
        ('assistant', 'Asistente'),
        ('system', 'Sistema'),
        ('tool_result', 'Resultado herramienta'),
    ], string='Rol', required=True)
    content = fields.Text('Contenido')
    tool_calls_json = fields.Text('Tool Calls (JSON)')
    tool_results_json = fields.Text('Tool Results (JSON)')
    create_date = fields.Datetime('Fecha', readonly=True)
    input_tokens = fields.Integer('Tokens entrada')
    output_tokens = fields.Integer('Tokens salida')
    total_tokens = fields.Integer('Tokens total', compute='_compute_total_tokens', store=True)

    price_1m_input_snapshot = fields.Float(
        'Precio Input snapshot', digits=(10, 4), readonly=True,
    )
    price_1m_output_snapshot = fields.Float(
        'Precio Output snapshot', digits=(10, 4), readonly=True,
    )
    cost_usd = fields.Float(
        'Costo (USD)', digits=(12, 6), readonly=True,
    )

    @api.depends('input_tokens', 'output_tokens')
    def _compute_total_tokens(self):
        for rec in self:
            rec.total_tokens = rec.input_tokens + rec.output_tokens
