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
    factura_electronica_tenant = fields.Boolean(
        string='Tenant factura',
        compute='_compute_factura_electronica_tenant',
        help='True si la suscripción del tenant (company) incluye facturación '
             'electrónica SRI. La vista de Clientes lo usa para mostrar u '
             'ocultar teléfono/celular/correo (datos requeridos solo si '
             'factura). Guarda suave: si el módulo de suscripciones no está '
             'instalado, queda False.',
    )

    @api.model
    def default_get(self, fields_list):
        """En la vista de Clientes, el país por defecto es el de la company
        (tenant). Se activa con el flag `cliente_default_pais` del contexto."""
        res = super().default_get(fields_list)
        if (self.env.context.get('cliente_default_pais')
                and 'country_id' in fields_list and not res.get('country_id')):
            country = self.env.company.country_id
            if country:
                res['country_id'] = country.id
        return res

    @api.depends('company_id')
    def _compute_factura_electronica_tenant(self):
        has_susc = 'in_agenda.suscripcion' in self.env
        Sus = self.env['in_agenda.suscripcion'].sudo() if has_susc else None
        for rec in self:
            if not has_susc:
                rec.factura_electronica_tenant = False
                continue
            company = rec.company_id or self.env.company
            rec.factura_electronica_tenant = Sus._company_has_feature(
                company, 'facturacion_sri')

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
