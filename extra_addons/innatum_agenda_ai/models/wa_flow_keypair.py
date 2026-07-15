# -*- coding: utf-8 -*-
from odoo import fields, models

from . import wa_flow_crypto


class InnatumWaFlowKeypair(models.Model):
    _name = 'innatum.wa.flow.keypair'
    _description = 'Par de claves RSA del Data Endpoint de WhatsApp Flows'

    company_id = fields.Many2one(
        'res.company', string='Tenant', required=True, index=True)
    private_key_pem = fields.Text(
        string='Clave privada (PEM)', groups='base.group_system',
        help='Descifra los requests del Flow de este tenant. NUNCA sale '
             'de Odoo.')
    public_key_pem = fields.Text(
        string='Clave pública (PEM)', readonly=True,
        help='Subirla a Meta: POST /{PHONE_NUMBER_ID}/'
             'whatsapp_business_encryption (guía FLOWS1_DESPLIEGUE.md).')
    generated_at = fields.Datetime(string='Generada el', readonly=True)

    _sql_constraints = [
        ('company_unique', 'unique(company_id)',
         'Ya existe un par de claves para este tenant.'),
    ]

    def action_generate(self):
        """(Re)genera el par. Regenerar invalida la clave subida a Meta:
        hay que volver a subir la pública."""
        for rec in self:
            priv, pub = wa_flow_crypto.generate_keypair_pem()
            rec.write({
                'private_key_pem': priv,
                'public_key_pem': pub,
                'generated_at': fields.Datetime.now(),
            })
        return True
