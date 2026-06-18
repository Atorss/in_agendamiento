# -*- coding: utf-8 -*-

import logging
from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InAgendaRecargaIA(models.Model):
    """Recarga de tokens IA sobre una suscripción.

    Cada recarga representa un cobro adicional al tenant por consumo de IA.
    Múltiples recargas coexisten en una suscripción; vigentes hasta agotar
    los tokens disponibles.

    Diferencia clave vs in_med.contrato.recarga_ia: las recargas viven a
    nivel suscripción/company, NO a nivel doctor individual. El FIFO se
    imputa contra el consumo total de la company.

    Lógica:
      tokens_disponibles_usd = monto_cobrado_usd × (1 - margen_pct_aplicado / 100)
      tokens_consumidos_usd  = consumo de la company desde la fecha de la
                               primera recarga, imputado FIFO
      tokens_restantes_usd   = disponibles - consumidos
      state                  = 'vigente' si restantes > 0, sino 'agotada'

    El margen se snapshotea al crear: cambios posteriores a ai_margin_pct
    en la suscripción NO afectan recargas existentes.
    """
    _name = 'in_agenda.recarga_ia'
    _description = 'Recarga de Tokens IA'
    _order = 'fecha desc, id desc'
    _rec_name = 'display_name'

    suscripcion_id = fields.Many2one(
        'in_agenda.suscripcion', string='Suscripción',
        required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(
        related='suscripcion_id.company_id', store=True, readonly=True,
        string='Tenant', index=True,
    )
    fecha = fields.Date(
        string='Fecha', required=True, default=fields.Date.today,
        help='Fecha en que se realizó la recarga. El consumo desde esta '
             'fecha cuenta contra el saldo.',
    )
    monto_cobrado_usd = fields.Float(
        string='Monto cobrado (USD)', required=True, digits=(12, 4),
        help='Lo que se le cobró al tenant. Ej: $10 = el tenant pagó $10 '
             'para usar IA.',
    )
    margen_pct_aplicado = fields.Float(
        string='Margen aplicado (%)', required=True, digits=(5, 2),
        readonly=True,
        help='Snapshot de suscripcion.ai_margin_pct al crear la recarga. '
             'Cambios posteriores NO afectan esta recarga.',
    )
    tokens_disponibles_usd = fields.Float(
        string='Disponibles (USD)',
        compute='_compute_tokens', store=True, digits=(12, 4),
        help='monto × (1 - margen%) — cap real de tokens al crear.',
    )
    tokens_consumidos_usd = fields.Float(
        string='Consumidos (USD)',
        compute='_compute_tokens', digits=(12, 4), store=False,
        help='Consumo de la company desde la fecha de la primera recarga, '
             'imputado FIFO hasta agotar disponibles.',
    )
    tokens_restantes_usd = fields.Float(
        string='Restantes (USD)',
        compute='_compute_tokens', digits=(12, 4), store=False,
    )
    state = fields.Selection([
        ('vigente', 'Vigente'),
        ('agotada', 'Agotada'),
    ], string='Estado', compute='_compute_tokens', store=False)
    # --- Vista para el admin del tenant (oculta el margen real) ---
    consumido_visible_usd = fields.Float(
        string='Consumido (vista tenant)',
        compute='_compute_tokens', digits=(12, 4), store=False,
        help='Consumo proporcional al monto cobrado. Lo que el admin del '
             'tenant ve, sin revelar el margen interno.',
    )
    restante_visible_usd = fields.Float(
        string='Restante (vista tenant)',
        compute='_compute_tokens', digits=(12, 4), store=False,
    )
    notes = fields.Text(string='Notas')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('fecha', 'monto_cobrado_usd')
    def _compute_display_name(self):
        for rec in self:
            if rec.fecha and rec.monto_cobrado_usd:
                rec.display_name = (
                    f"Recarga {rec.fecha} — ${rec.monto_cobrado_usd:.2f}"
                )
            else:
                rec.display_name = 'Nueva recarga'

    @api.depends('monto_cobrado_usd', 'margen_pct_aplicado', 'fecha',
                 'suscripcion_id', 'company_id')
    def _compute_tokens(self):
        """Calcula consumido/restantes con imputación FIFO por suscripción.

        Las recargas de una suscripción se ordenan por fecha ASC y el
        consumo total de la company (desde la fecha de la PRIMERA recarga)
        se imputa contra cada recarga en orden hasta agotarla.
        """
        UsageLog = self.env.get('innatum.ai.usage.log')

        # 1. Disponibles (siempre)
        for rec in self:
            factor = max(0.0, 1.0 - (rec.margen_pct_aplicado or 0.0) / 100.0)
            rec.tokens_disponibles_usd = (rec.monto_cobrado_usd or 0.0) * factor

        # 2. Si IA no instalada, todo vigente con 0 consumo
        if UsageLog is None:
            for rec in self:
                rec.tokens_consumidos_usd = 0.0
                rec.tokens_restantes_usd = rec.tokens_disponibles_usd
                rec.consumido_visible_usd = 0.0
                rec.restante_visible_usd = rec.monto_cobrado_usd or 0.0
                rec.state = 'vigente' if rec.tokens_disponibles_usd > 0 else 'agotada'
            return

        # 3. Agrupar self por suscripción
        suscripciones = {}
        for rec in self:
            if rec.suscripcion_id.id:
                suscripciones.setdefault(rec.suscripcion_id.id, self.env[self._name])
                suscripciones[rec.suscripcion_id.id] |= rec

        UsageLog = UsageLog.sudo()
        procesadas = self.env[self._name]

        for sus_id, _recs in suscripciones.items():
            todas = self.sudo().search(
                [('suscripcion_id', '=', sus_id)],
                order='fecha asc, id asc',
            )
            if not todas:
                continue
            # Asegurar disponibles calculado para recargas no incluidas en self
            for r in todas:
                if r.id not in self.ids:
                    factor = max(0.0, 1.0 - (r.margen_pct_aplicado or 0.0) / 100.0)
                    r.tokens_disponibles_usd = (r.monto_cobrado_usd or 0.0) * factor

            company = todas[0].company_id
            primera_fecha = todas[0].fecha
            if not company or not primera_fecha:
                for r in todas:
                    r.tokens_consumidos_usd = 0.0
                    r.tokens_restantes_usd = r.tokens_disponibles_usd
                    r.consumido_visible_usd = 0.0
                    r.restante_visible_usd = r.monto_cobrado_usd or 0.0
                    r.state = 'vigente' if r.tokens_disponibles_usd > 0 else 'agotada'
                    procesadas |= r
                continue

            # Consumo total de la company desde la primera recarga
            fecha_dt = fields.Datetime.to_string(
                datetime.combine(primera_fecha, datetime.min.time())
            )
            logs = UsageLog.search([
                ('company_id', '=', company.id),
                ('create_date', '>=', fecha_dt),
            ])
            consumo_total = sum(logs.mapped('cost_usd'))

            # FIFO
            remaining = consumo_total
            for r in todas:
                disp = r.tokens_disponibles_usd or 0.0
                consumido = min(remaining, disp)
                r.tokens_consumidos_usd = consumido
                r.tokens_restantes_usd = max(0.0, disp - consumido)
                cobrado = r.monto_cobrado_usd or 0.0
                if disp > 0:
                    pct = consumido / disp
                    r.consumido_visible_usd = pct * cobrado
                    r.restante_visible_usd = max(0.0, cobrado - r.consumido_visible_usd)
                else:
                    r.consumido_visible_usd = 0.0
                    r.restante_visible_usd = cobrado
                r.state = 'vigente' if r.tokens_restantes_usd > 0 else 'agotada'
                remaining -= consumido
                procesadas |= r

        # 4. Recargas sin suscripción (defensivo)
        for rec in self - procesadas:
            rec.tokens_consumidos_usd = 0.0
            rec.tokens_restantes_usd = rec.tokens_disponibles_usd
            rec.consumido_visible_usd = 0.0
            rec.restante_visible_usd = rec.monto_cobrado_usd or 0.0
            rec.state = 'vigente' if rec.tokens_disponibles_usd > 0 else 'agotada'

    @api.model_create_multi
    def create(self, vals_list):
        """Snapshot del margen actual de la suscripción al crear."""
        Sus = self.env['in_agenda.suscripcion'].sudo()
        for vals in vals_list:
            if 'margen_pct_aplicado' not in vals and vals.get('suscripcion_id'):
                sus = Sus.browse(vals['suscripcion_id'])
                vals['margen_pct_aplicado'] = sus.ai_margin_pct or 0.0
        return super().create(vals_list)

    @api.constrains('monto_cobrado_usd')
    def _check_monto_positivo(self):
        for rec in self:
            if rec.monto_cobrado_usd <= 0:
                raise ValidationError('El monto cobrado debe ser mayor a 0.')

    @api.constrains('margen_pct_aplicado')
    def _check_margin(self):
        for rec in self:
            if not (0 <= rec.margen_pct_aplicado <= 100):
                raise ValidationError(
                    'El margen aplicado debe estar entre 0 y 100%.'
                )
