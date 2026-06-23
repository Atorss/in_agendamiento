# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # --- Límites de consumo IA (nivel instancia) ---
    innatum_ai_monthly_limit_usd = fields.Float(
        string='Límite Mensual (USD)',
        config_parameter='innatum_ai.monthly_limit_usd',
        default=5.0,
        help='Presupuesto máximo de gasto en APIs de IA por mes natural '
             '(toda la instancia). Al alcanzarlo se bloquean nuevas '
             'llamadas hasta el siguiente mes.',
    )
    innatum_ai_max_cost_per_conversation_usd = fields.Float(
        string='Límite por Conversación (USD)',
        config_parameter='innatum_ai.max_cost_per_conversation_usd',
        default=0.10,
        help='Presupuesto máximo de una sola conversación. Evita loops '
             'infinitos o abuso por un solo usuario.',
    )
    innatum_ai_limit_action = fields.Selection(
        selection=[
            ('block', 'Bloquear (levantar error al usuario)'),
            ('warn', 'Sólo advertir (log + permitir continuar)'),
        ],
        string='Acción al Alcanzar Límite',
        config_parameter='innatum_ai.limit_action',
        default='block',
    )

    # --- Consumo actual (informativo) ---
    innatum_ai_current_month_cost_usd = fields.Float(
        string='Consumo del Mes (USD)',
        compute='_compute_current_innatum_ai_usage',
        digits=(12, 4),
    )
    innatum_ai_current_month_pct = fields.Float(
        string='% Consumido del Mes',
        compute='_compute_current_innatum_ai_usage',
    )

    @api.depends('innatum_ai_monthly_limit_usd')
    def _compute_current_innatum_ai_usage(self):
        from datetime import datetime
        for rec in self:
            month_start = fields.Date.today().replace(day=1)
            logs = self.env['innatum.ai.usage.log'].sudo().search([
                ('create_date', '>=', fields.Datetime.to_string(
                    datetime.combine(month_start, datetime.min.time())
                )),
            ])
            cost = sum(logs.mapped('cost_usd'))
            rec.innatum_ai_current_month_cost_usd = cost
            rec.innatum_ai_current_month_pct = (
                (cost / rec.innatum_ai_monthly_limit_usd) * 100
                if rec.innatum_ai_monthly_limit_usd else 0
            )
