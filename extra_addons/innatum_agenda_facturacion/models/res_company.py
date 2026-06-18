# -*- coding: utf-8 -*-

from odoo import models, _


class ResCompany(models.Model):
    _inherit = 'res.company'

    def action_open_ec_localization(self):
        """Abre el form de localización ecuatoriana de la empresa actual:
        razón social, régimen, certificado SRI, etc."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Localización Ecuatoriana'),
            'res_model': 'res.company',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'innatum_agenda_facturacion.res_company_localizacion_ec_form'
            ).id,
            'res_id': self.id,
            'target': 'current',
            'context': {
                'create': False,
                'edit': True,
                'delete': False,
                'duplicate': False,
                'form_view_initial_mode': 'edit',
            },
        }
