# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    servicios_consumidos_ids = fields.Many2many(
        'innatum.agenda.servicio',
        'innatum_agenda_partner_servicio_rel',
        'partner_id', 'servicio_id',
        string='Servicios consumidos',
        help='Servicios que el cliente ha solicitado en este tenant. '
             'Se completa automáticamente al reservar turnos.',
    )

    @api.constrains('vat', 'company_id')
    def _check_vat_unique(self):
        """Impide registrar dos contactos con el mismo VAT (cédula/RUC)
        dentro de la misma company (tenant). Permite que el mismo VAT
        exista en companies distintas — cada tenant ve su propio cliente."""
        for rec in self:
            vat = (rec.vat or '').strip()
            if not vat:
                continue
            domain = [
                ('id', '!=', rec.id),
                ('vat', '=', vat),
            ]
            if rec.company_id:
                domain.append(('company_id', '=', rec.company_id.id))
            else:
                domain.append(('company_id', '=', False))
            duplicate = self.sudo().search(domain, limit=1)
            if duplicate:
                raise ValidationError(
                    'Ya existe otro contacto con la identificación '
                    '"%s": "%s" (id %d). No se permite duplicar.' % (
                        vat, duplicate.name, duplicate.id,
                    )
                )
