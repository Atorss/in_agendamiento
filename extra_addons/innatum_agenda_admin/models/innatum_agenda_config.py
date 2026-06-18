# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo.exceptions import UserError


class InnatumAgendaConfig(models.Model):
    _inherit = 'innatum.agenda.config'

    @api.model_create_multi
    def create(self, vals_list):
        """Bloquea la creación de planificaciones para usuarios con rol
        Usuario que NO tienen el flag puede_planificar habilitado.
        Operador y Admin siempre pueden crear."""
        user = self.env.user
        is_op_or_admin = user.has_group(
            'innatum_agenda_core.innatum_agenda_group_operator'
        )
        if not is_op_or_admin:
            employee = self.env['hr.employee'].sudo().search([
                ('user_id', '=', user.id),
            ], limit=1)
            if not employee or not employee.puede_planificar:
                raise UserError(_(
                    'No tienes permiso para crear planificaciones. '
                    'Pídele al administrador que active "Puede crear su '
                    'planificación" en tu ficha de empleado.'
                ))
        return super().create(vals_list)
