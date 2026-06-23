# -*- coding: utf-8 -*-
"""Log único de TODAS las llamadas a APIs de IA en la instancia.

Fuente autoritativa del cálculo de costos para el enforcement del límite
mensual. Cada llamada exitosa a un provider (Anthropic, OpenAI, Google) se
registra aquí automáticamente desde el motor (innatum.ai.engine), sin
importar si vino del chatbot, del generador de reportes, etc.
"""

from odoo import models, fields, api


class AIUsageLog(models.Model):
    _name = 'innatum.ai.usage.log'
    _description = 'Log de uso de IA'
    _order = 'create_date desc'
    _rec_name = 'source'

    create_date = fields.Datetime('Fecha', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Empresa', required=True, index=True,
        default=lambda self: self.env.company,
    )
    provider_id = fields.Many2one(
        'innatum.ai.provider', string='Proveedor',
        ondelete='set null', index=True,
    )
    model = fields.Char('Modelo', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Usuario', index=True,
        default=lambda self: self.env.user,
    )
    source = fields.Char(
        'Origen', required=True, index=True,
        help='Dónde se originó la llamada. Valores típicos:\n'
             '- chatbot_web: Chatbot público /chatbot\n'
             '- test_connection: Prueba de configuración\n'
             '- vision_completion: Análisis de imagen\n'
             '- sql_report: Consulta SQL generada por IA\n'
             '- unknown: Origen no identificado',
    )
    record_ref = fields.Char(
        'Ref Record', help='res_model,res_id del registro que originó la llamada (opcional)',
    )

    input_tokens = fields.Integer('Tokens Entrada', readonly=True)
    output_tokens = fields.Integer('Tokens Salida', readonly=True)
    total_tokens = fields.Integer(
        'Tokens Total', compute='_compute_total_tokens', store=True,
    )

    price_1m_input_snapshot = fields.Float(
        'Precio Input (USD/1M)', digits=(10, 4), readonly=True,
    )
    price_1m_output_snapshot = fields.Float(
        'Precio Output (USD/1M)', digits=(10, 4), readonly=True,
    )
    cost_usd = fields.Float(
        'Costo (USD)', digits=(12, 6), readonly=True, index=True,
    )

    @api.depends('input_tokens', 'output_tokens')
    def _compute_total_tokens(self):
        for rec in self:
            rec.total_tokens = rec.input_tokens + rec.output_tokens
