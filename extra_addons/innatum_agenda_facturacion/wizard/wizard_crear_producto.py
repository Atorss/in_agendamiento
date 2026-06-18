# -*- coding: utf-8 -*-

from odoo import models, fields, _
from odoo.exceptions import UserError


class WizardCrearProducto(models.TransientModel):
    _name = 'innatum.agenda.facturacion.wizard.crear_producto'
    _description = 'Crear producto de facturación para un servicio'

    servicio_id = fields.Many2one(
        'innatum.agenda.servicio', string='Servicio',
        required=True, readonly=True,
    )
    servicio_name = fields.Char(
        related='servicio_id.name', string='Nombre del servicio', readonly=True,
    )
    precio = fields.Float(
        string='Precio', required=True,
        help='Precio de venta del producto. Quedará vinculado al servicio.',
    )

    def action_confirmar(self):
        self.ensure_one()
        if self.servicio_id.product_id:
            raise UserError(_(
                'El servicio "%s" ya tiene un producto asociado.'
            ) % self.servicio_id.name)
        self.servicio_id._crear_producto(precio=self.precio)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Producto creado'),
                'message': _('Se creó el producto de facturación con precio %s.') % self.precio,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
