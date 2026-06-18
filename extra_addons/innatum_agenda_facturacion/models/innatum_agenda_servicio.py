# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class InnatumAgendaServicio(models.Model):
    _inherit = 'innatum.agenda.servicio'

    product_id = fields.Many2one(
        'product.product', string='Producto de Facturación',
        domain="[('type', '=', 'service')]",
        copy=False,
        help='Producto vinculado al servicio. Se crea automáticamente al '
             'guardar el servicio o desde el botón "Crear Producto".',
    )
    precio = fields.Float(
        string='Precio',
        help='Precio de referencia del servicio. Si hay un producto asociado, '
             'se sincroniza con su precio de venta.',
    )

    def _crear_producto(self, precio=None):
        """Crea el product.product asociado al servicio y lo vincula.
        Si se pasa precio, además actualiza el campo precio del servicio.
        """
        self.ensure_one()
        if self.product_id:
            return self.product_id
        if precio is not None and precio != self.precio:
            self.sudo().write({'precio': precio})
        product = self.env['product.product'].sudo().create({
            'name': self.name,
            'type': 'service',
            'list_price': self.precio or 0.0,
            'sale_ok': True,
            'purchase_ok': False,
        })
        self.sudo().write({'product_id': product.id})
        _logger.info(
            'innatum_agenda_facturacion: producto "%s" (id=%d) creado para servicio id=%d (precio=%s)',
            self.name, product.id, self.id, self.precio,
        )
        return product

    def action_crear_producto(self):
        """Abre el wizard para definir el precio y crear el producto."""
        self.ensure_one()
        if self.product_id:
            raise UserError(_(
                'El servicio "%s" ya tiene un producto asociado.'
            ) % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear Producto de Facturación'),
            'res_model': 'innatum.agenda.facturacion.wizard.crear_producto',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_servicio_id': self.id,
                'default_precio': self.precio or 0.0,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-crea un product.product para cada servicio nuevo si no
        viene uno explícito. Usa vals['precio'] como list_price del producto."""
        Product = self.env['product.product'].sudo()
        for vals in vals_list:
            if vals.get('product_id') or not vals.get('name'):
                continue
            precio = vals.get('precio', 0.0) or 0.0
            product = Product.create({
                'name': vals['name'],
                'type': 'service',
                'list_price': precio,
                'sale_ok': True,
                'purchase_ok': False,
            })
            vals['product_id'] = product.id
            _logger.info(
                'innatum_agenda_facturacion: producto "%s" (id=%d) creado para servicio "%s" (precio=%s)',
                vals['name'], product.id, vals['name'], precio,
            )
        return super().create(vals_list)

    def write(self, vals):
        """Sincroniza name y precio del servicio con el producto vinculado."""
        result = super().write(vals)
        if 'name' in vals:
            for rec in self.filtered('product_id'):
                rec.product_id.sudo().write({'name': vals['name']})
        if 'precio' in vals:
            for rec in self.filtered('product_id'):
                rec.product_id.sudo().write({'list_price': vals['precio']})
        return result
