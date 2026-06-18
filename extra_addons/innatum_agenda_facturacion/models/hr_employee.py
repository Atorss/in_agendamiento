# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

PUEDE_FACTURAR_GROUP_XMLID = (
    'innatum_agenda_facturacion.innatum_agenda_group_puede_facturar'
)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    puede_facturar = fields.Boolean(
        string='Puede facturar', default=False,
        help='Si está activo, este empleado puede crear pedidos de venta '
             'desde sus turnos aunque su rol sea solo "Usuario".\n\n'
             'Le otorga ACL mínima sobre sale.order limitada por record-rule '
             'a sus propios turnos. No le asigna grupos de Ventas ni '
             'Contabilidad: no verá esos menús.\n\n'
             'Operador y Administrador siempre pueden facturar, sin importar '
             'este flag.',
    )

    def _innatum_facturacion_sync_groups(self):
        """Sincroniza el grupo técnico 'Puede facturar' del res.users
        vinculado con el flag puede_facturar del empleado."""
        group = self.env.ref(PUEDE_FACTURAR_GROUP_XMLID, raise_if_not_found=False)
        if not group:
            return
        for emp in self.filtered(lambda e: e.user_id):
            command = [(4, group.id)] if emp.puede_facturar else [(3, group.id)]
            emp.user_id.sudo().write({'groups_id': command})
            _logger.info(
                'innatum_agenda_facturacion: grupo "Puede facturar" %s '
                'para usuario id=%d (empleado "%s")',
                'asignado' if emp.puede_facturar else 'revocado',
                emp.user_id.id, emp.name,
            )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._innatum_facturacion_sync_groups()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if 'puede_facturar' in vals or 'user_id' in vals:
            self._innatum_facturacion_sync_groups()
        return result
