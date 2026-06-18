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
    max_turnos_mes = fields.Integer(
        string='Turnos / mes (0=ilimitado)', default=0,
        help='Cantidad máxima de turnos disponibles que el tenant puede '
             'generar por mes. 0 = sin límite.',
    )
    max_profesionales = fields.Integer(
        string='Profesionales (0=ilimitado)', default=0,
        help='Cantidad máxima de empleados profesionales en el tenant. '
             '0 = sin límite.',
    )
    ai_enabled = fields.Boolean(
        string='IA habilitada', default=True,
        help='Si está activo, el tenant puede usar el chatbot IA contra el '
             'saldo de sus recargas. Si no, las features de IA quedan '
             'inhabilitadas para el tenant.',
    )
    ai_margin_pct_default = fields.Float(
        string='Margen IA % (default)', default=50.0, digits=(5, 2),
        help='Porcentaje de utilidad para Innatum sobre las recargas IA. '
             'Ej: 50 = el cliente cobra $10 → $5 son tokens consumibles, $5 '
             'son utilidad de Innatum. Snapshot al crear suscripción.',
    )
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'El código del plan debe ser único.'),
    ]

    @api.constrains('ai_margin_pct_default')
    def _check_margin(self):
        for rec in self:
            if not (0 <= rec.ai_margin_pct_default <= 100):
                raise ValidationError(
                    'El margen IA debe estar entre 0 y 100%.'
                )

    @api.constrains('precio_mensual_usd', 'max_turnos_mes', 'max_profesionales')
    def _check_positivos(self):
        for rec in self:
            if rec.precio_mensual_usd < 0:
                raise ValidationError('El precio mensual no puede ser negativo.')
            if rec.max_turnos_mes < 0:
                raise ValidationError('El límite de turnos no puede ser negativo.')
            if rec.max_profesionales < 0:
                raise ValidationError('El límite de profesionales no puede ser negativo.')
