# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models


class ResCompanyFlow(models.Model):
    _inherit = 'res.company'

    wa_flow_id = fields.Char(
        string='Flow ID (agendamiento)',
        help='ID del Flow publicado en el WABA del tenant. Vacío = el '
             'agente usa el funnel de listas.')
    wa_flow_slug = fields.Char(
        string='Slug del Data Endpoint', copy=False, readonly=True,
        help='Identifica al tenant en la ruta /whatsapp/flow/data/<slug>.')

    _sql_constraints = [
        ('wa_flow_slug_unique', 'unique(wa_flow_slug)',
         'El slug del endpoint de Flows debe ser único.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: not r.wa_flow_slug):
            rec.wa_flow_slug = secrets.token_urlsafe(9)
        return records

    def init(self):
        # Backfill para companies existentes al actualizar el módulo.
        for rec in self.sudo().search([('wa_flow_slug', '=', False)]):
            rec.wa_flow_slug = secrets.token_urlsafe(9)
