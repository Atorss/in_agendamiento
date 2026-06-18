# -*- coding: utf-8 -*-
"""Extensión de hr.employee para gestión SaaS de colaboradores.

El admin del tenant NO tiene permisos write/unlink directos sobre
hr.employee — solo read. Estos botones permiten desactivar/reactivar
colaboradores vía métodos que corren con sudo internamente, validando
que el caller pertenezca al tenant correcto.
"""

import logging

from odoo import models, _
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _check_caller_can_manage(self):
        """El caller debe tener el grupo Administrador de Agenda."""
        if not self.env.user.has_group(
            'innatum_agenda_core.innatum_agenda_group_admin'
        ):
            raise AccessError(_(
                'Solo el Administrador de Agenda puede gestionar '
                'colaboradores.'
            ))

    def _check_belongs_to_my_tenant(self):
        """El colaborador debe pertenecer a una company del caller."""
        for emp in self:
            if emp.company_id and emp.company_id.id not in self.env.user.company_ids.ids:
                raise ValidationError(_(
                    'No tienes acceso a este colaborador (pertenece a otra '
                    'empresa).'
                ))

    def action_desactivar_colaborador(self):
        """Desactiva el colaborador y su usuario asociado.

        Corre con sudo después de validar permisos. El colaborador queda
        inactivo: no puede iniciar sesión ni aparece en planificaciones.
        Reversible vía action_reactivar_colaborador.
        """
        self._check_caller_can_manage()
        self._check_belongs_to_my_tenant()
        for emp in self:
            emp.sudo().write({'active': False})
            if emp.user_id:
                emp.user_id.sudo().write({'active': False})
            _logger.info(
                'Colaborador desactivado: emp=%s user=%s (por %s)',
                emp.id, emp.user_id.id if emp.user_id else None,
                self.env.user.login,
            )
        return True

    def action_reactivar_colaborador(self):
        """Reactiva un colaborador previamente desactivado."""
        self._check_caller_can_manage()
        # Para reactivar inactivos, necesitamos with_context(active_test=False)
        emps = self.with_context(active_test=False)
        emps._check_belongs_to_my_tenant()
        for emp in emps:
            emp.sudo().write({'active': True})
            if emp.user_id:
                emp.sudo().user_id.write({'active': True})
            _logger.info(
                'Colaborador reactivado: emp=%s (por %s)',
                emp.id, self.env.user.login,
            )
        return True
