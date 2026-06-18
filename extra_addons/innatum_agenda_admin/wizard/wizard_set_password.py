# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class WizardSetPassword(models.TransientModel):
    _name = 'innatum.agenda.admin.wizard.set_password'
    _description = 'Establecer contraseña de empleado'

    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', required=True,
        readonly=True,
    )
    user_login = fields.Char(
        string='Usuario (login)', related='employee_id.user_id.login',
        readonly=True,
    )
    password = fields.Char(
        string='Nueva Contraseña', required=True,
    )
    password_confirm = fields.Char(
        string='Confirmar Contraseña', required=True,
    )

    @api.constrains('password', 'password_confirm')
    def _check_password(self):
        for rec in self:
            if rec.password != rec.password_confirm:
                raise ValidationError('Las contraseñas no coinciden.')
            if len(rec.password or '') < 6:
                raise ValidationError(
                    'La contraseña debe tener al menos 6 caracteres.'
                )

    def action_set_password(self):
        self.ensure_one()
        if not self.employee_id.user_id:
            raise UserError(
                'Este empleado no tiene un usuario vinculado. '
                'Crea primero el usuario actualizando su correo de trabajo.'
            )
        self.employee_id.user_id.sudo().write({'password': self.password})
        _logger.info(
            'innatum_agenda_admin: contraseña actualizada para usuario %s (id=%d)',
            self.employee_id.user_id.login, self.employee_id.user_id.id,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Contraseña actualizada',
                'message': f'Se asignó una nueva contraseña a {self.employee_id.name}.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
