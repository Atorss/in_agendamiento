from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    in_edi_environment = fields.Selection(
        related="company_id.in_edi_environment", readonly=False
    )
    in_edi_obligado_contabilidad = fields.Boolean(
        related="company_id.in_edi_obligado_contabilidad", readonly=False
    )
    in_edi_contribuyente_especial = fields.Char(
        related="company_id.in_edi_contribuyente_especial", readonly=False
    )
    in_edi_razon_social = fields.Char(
        related="company_id.in_edi_razon_social", readonly=False
    )
    in_edi_nombre_comercial = fields.Char(
        related="company_id.in_edi_nombre_comercial", readonly=False
    )
    in_edi_dir_matriz = fields.Char(
        related="company_id.in_edi_dir_matriz", readonly=False
    )
