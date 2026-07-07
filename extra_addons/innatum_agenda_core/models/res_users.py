# -*- coding: utf-8 -*-
from odoo import api, models


class ResUsers(models.Model):
    """Sincroniza los grupos técnicos de modo de agenda del usuario según la
    empresa a la que pertenece (company_id.agenda_modo).

    Estos grupos controlan la visibilidad de los menús específicos de cada
    modo (Planificación en 'planificada', Bloqueos en 'directa'). El usuario
    NO debe asignarlos a mano; se mantienen automáticamente aquí y en
    res.company.write (cuando el tenant cambia de modo).
    """
    _inherit = 'res.users'

    def _innatum_sync_agenda_modo_group(self):
        """Coloca a cada usuario en el grupo del modo de su empresa y lo saca
        del otro. Ignora usuarios externos (portal/público)."""
        planif = self.env.ref(
            'innatum_agenda_core.innatum_agenda_group_modo_planificada',
            raise_if_not_found=False,
        )
        directa = self.env.ref(
            'innatum_agenda_core.innatum_agenda_group_modo_directa',
            raise_if_not_found=False,
        )
        if not planif or not directa:
            return
        for user in self:
            # share = usuarios portal/público: no ven el backend, se omiten.
            if user.share:
                continue
            modo = user.company_id.agenda_modo
            if modo == 'directa':
                directa.sudo().write({'users': [(4, user.id)]})
                planif.sudo().write({'users': [(3, user.id)]})
            else:
                planif.sudo().write({'users': [(4, user.id)]})
                directa.sudo().write({'users': [(3, user.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._innatum_sync_agenda_modo_group()
        return users

    def write(self, vals):
        res = super().write(vals)
        # Si cambia la empresa por defecto del usuario, re-evalúa su modo.
        if 'company_id' in vals:
            self._innatum_sync_agenda_modo_group()
        return res
