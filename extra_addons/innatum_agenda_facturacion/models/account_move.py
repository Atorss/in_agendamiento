# -*- coding: utf-8 -*-

from odoo import models, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_ec_sri_payment_id = fields.Many2one(
        default=lambda self: self.env.ref(
            'l10n_ec.P20', raise_if_not_found=False,
        ),
    )
