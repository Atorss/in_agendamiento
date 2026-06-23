# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InAgendaPlan(models.Model):
    """Catálogo de planes que Innatum vende a sus clientes (tenants).

    Cada plan define límites operativos y un margen IA default. Al crear una
    suscripción, los valores del plan se SNAPSHOTEAN: cambios posteriores al
    plan no afectan suscripciones existentes.
    """
    _name = 'in_agenda.plan'
    _description = 'Plan de Suscripción'
    _order = 'precio_mensual_usd asc, name'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(
        string='Código', required=True,
        help='Identificador corto único, ej: "BASIC", "PRO", "ENT".',
    )
    precio_mensual_usd = fields.Float(
        string='Precio mensual (USD)', required=True, digits=(12, 2),
        default=0.0,
    )
    max_profesionales = fields.Integer(
        string='Profesionales (0=ilimitado)', default=0,
        help='Cantidad máxima de empleados profesionales en el tenant. '
             '0 = sin límite.',
    )
    ai_margin_pct_default = fields.Float(
        string='Margen IA % (default)', default=50.0, digits=(5, 2),
        help='Porcentaje de utilidad para Innatum sobre las recargas IA. '
             'Ej: 50 = el cliente cobra $10 → $5 son tokens consumibles, $5 '
             'son utilidad de Innatum. Snapshot al crear suscripción.',
    )
    # --- Facturación anual (descuento híbrido: meses gratis O porcentaje) ---
    descuento_anual_tipo = fields.Selection([
        ('ninguno', 'Sin descuento'),
        ('meses', 'Meses gratis'),
        ('porcentaje', 'Porcentaje'),
    ], string='Tipo de descuento anual', default='meses', required=True,
        help='Cómo se calcula el precio anual respecto al mensual.')
    descuento_anual_meses = fields.Integer(
        string='Meses gratis al año', default=2,
        help='Solo si el tipo es "Meses gratis": precio anual = mensual × '
             '(12 − meses). Ej: 2 → el cliente paga 10 meses.')
    descuento_anual_pct = fields.Float(
        string='Descuento anual (%)', digits=(5, 2), default=0.0,
        help='Solo si el tipo es "Porcentaje": precio anual = mensual × 12 × '
             '(1 − %/100).')
    precio_anual_usd = fields.Float(
        string='Precio anual (USD)', compute='_compute_precio_anual',
        store=True, digits=(12, 2),
        help='Precio anual efectivo según el descuento configurado.')
    ahorro_anual_usd = fields.Float(
        string='Ahorro anual (USD)', compute='_compute_precio_anual',
        store=True, digits=(12, 2),
        help='Cuánto ahorra el cliente pagando anual vs 12 meses sueltos.')
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'El código del plan debe ser único.'),
    ]

    @api.depends('precio_mensual_usd', 'descuento_anual_tipo',
                 'descuento_anual_meses', 'descuento_anual_pct')
    def _compute_precio_anual(self):
        for rec in self:
            base = rec.precio_mensual_usd * 12
            if rec.descuento_anual_tipo == 'meses':
                meses = max(0, min(12, rec.descuento_anual_meses))
                anual = rec.precio_mensual_usd * (12 - meses)
            elif rec.descuento_anual_tipo == 'porcentaje':
                pct = max(0.0, min(100.0, rec.descuento_anual_pct))
                anual = base * (1 - pct / 100.0)
            else:
                anual = base
            rec.precio_anual_usd = anual
            rec.ahorro_anual_usd = base - anual

    @api.constrains('descuento_anual_meses', 'descuento_anual_pct')
    def _check_descuento_anual(self):
        for rec in self:
            if not (0 <= rec.descuento_anual_meses <= 12):
                raise ValidationError('Los meses gratis deben estar entre 0 y 12.')
            if not (0 <= rec.descuento_anual_pct <= 100):
                raise ValidationError('El descuento anual % debe estar entre 0 y 100.')

    @api.constrains('ai_margin_pct_default')
    def _check_margin(self):
        for rec in self:
            if not (0 <= rec.ai_margin_pct_default <= 100):
                raise ValidationError(
                    'El margen IA debe estar entre 0 y 100%.'
                )

    @api.constrains('precio_mensual_usd', 'max_profesionales')
    def _check_positivos(self):
        for rec in self:
            if rec.precio_mensual_usd < 0:
                raise ValidationError('El precio mensual no puede ser negativo.')
            if rec.max_profesionales < 0:
                raise ValidationError('El límite de profesionales no puede ser negativo.')
