# -*- coding: utf-8 -*-
"""Número WhatsApp normalizado del empleado (Fase 2).

Permite identificar mensajes entrantes de STAFF con un search directo e
indexado, sin normalizar en caliente en cada mensaje.
"""
from odoo import api, fields, models


class HrEmployeeWa(models.Model):
    _inherit = 'hr.employee'

    wa_number_normalized = fields.Char(
        string='WhatsApp normalizado',
        compute='_compute_wa_number_normalized', store=True, index=True,
        help='Celular del empleado en formato Meta (5939XXXXXXXX), calculado '
             'con la misma normalización del canal saliente. Se usa para '
             'reconocer mensajes entrantes del staff.',
    )

    @api.depends('mobile_phone', 'work_phone')
    def _compute_wa_number_normalized(self):
        Outbound = self.env['innatum.wa.outbound']
        for emp in self:
            emp.wa_number_normalized = Outbound.normalize_ec_number(
                emp.mobile_phone or emp.work_phone) or False
