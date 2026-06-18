# -*- coding: utf-8 -*-

from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    innatum_turno_ids = fields.One2many(
        'innatum.agenda.turno', 'sale_order_id',
        string='Turnos asociados',
    )
