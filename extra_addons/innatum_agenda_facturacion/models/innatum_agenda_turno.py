# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class InnatumAgendaTurno(models.Model):
    _inherit = 'innatum.agenda.turno'

    sale_order_id = fields.Many2one(
        'sale.order', string='Pedido de venta',
        copy=False, readonly=True, tracking=True,
        help='Pedido de venta generado para facturar este turno.',
    )
    sale_order_state = fields.Selection(
        related='sale_order_id.state', string='Estado del pedido', readonly=True,
    )
    can_facturar = fields.Boolean(
        compute='_compute_can_facturar',
        help='True si el usuario logueado puede facturar este turno.',
    )

    def _compute_can_facturar(self):
        user = self.env.user
        is_op_or_admin = user.has_group(
            'innatum_agenda_core.innatum_agenda_group_operator'
        )
        own_employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id),
        ], limit=1)
        puede_facturar_propio = bool(own_employee and own_employee.puede_facturar)
        for rec in self:
            base_ok = (
                not rec.sale_order_id
                and rec.state in ('confirmed', 'done')
                and bool(rec.partner_id)
                and bool(rec.servicio_id)
            )
            if not base_ok:
                rec.can_facturar = False
                continue
            if is_op_or_admin:
                rec.can_facturar = True
            else:
                # Solo Usuario: debe tener flag puede_facturar Y ser el profesional del turno
                rec.can_facturar = (
                    puede_facturar_propio
                    and own_employee
                    and rec.professional_id == own_employee
                )

    def action_facturar(self):
        """Crea un sale.order con la línea del servicio asociado al turno."""
        self.ensure_one()
        if self.sale_order_id:
            return self.action_view_sale_order()

        if not self.partner_id:
            raise UserError(_("El turno no tiene cliente asignado."))
        if not self.servicio_id:
            raise UserError(_("El turno no tiene servicio asignado."))
        if not self.servicio_id.product_id:
            raise UserError(_(
                'El servicio "%s" no tiene producto de facturación. '
                'Edita el servicio y guarda para que se genere automáticamente.'
            ) % self.servicio_id.name)
        if self.state not in ('confirmed', 'done'):
            raise UserError(_(
                "Solo se puede facturar un turno en estado Confirmado o Finalizado."
            ))

        product = self.servicio_id.product_id
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'company_id': self.company_id.id or self.env.company.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': product.name,
                'product_uom_qty': 1,
                'price_unit': product.lst_price,
            })],
        })
        self.sale_order_id = order.id
        _logger.info(
            'innatum_agenda_facturacion: sale.order %s creado desde turno %s',
            order.name, self.name,
        )
        return self.action_view_sale_order()

    def action_view_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_("Este turno no tiene pedido de venta asociado."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pedido de venta'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }
