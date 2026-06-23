from odoo import api, fields, models, _


class ResCompany(models.Model):
    _inherit = "res.company"

    # --- Integración SaaS: gate por suscripción + smart button de firma ---
    tiene_facturacion_sri = fields.Boolean(
        string="Facturación SRI habilitada",
        compute="_compute_tiene_facturacion_sri",
        help="True si la suscripción del tenant tiene activada la facturación "
        "electrónica. Controla la visibilidad de la config SRI en el form.",
    )
    in_edi_certificate_count = fields.Integer(
        string="Certificados SRI", compute="_compute_in_edi_certificate_count")

    def _compute_tiene_facturacion_sri(self):
        # Guarda suave: si el módulo de suscripciones no está, queda False.
        has = "in_agenda.suscripcion" in self.env
        Sus = self.env["in_agenda.suscripcion"].sudo() if has else None
        for company in self:
            company.tiene_facturacion_sri = bool(
                has and Sus._company_has_feature(company, "facturacion_sri"))

    def _compute_in_edi_certificate_count(self):
        Cert = self.env["in_edi.certificate"].sudo()
        for company in self:
            company.in_edi_certificate_count = Cert.search_count(
                [("company_id", "=", company.id)])

    def action_open_in_edi_certificates(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Firma electrónica (SRI)"),
            "res_model": "in_edi.certificate",
            "view_mode": "list,form",
            "domain": [("company_id", "=", self.id)],
            "context": {"default_company_id": self.id},
        }

    in_edi_environment = fields.Selection(
        selection=[("1", "Test (Pruebas)"), ("2", "Production (Producción)")],
        string="SRI Environment",
        default="1",
        help="SRI environment used to build the access key and choose the web "
        "service endpoints. Keep on Test until certification is complete.",
    )
    in_edi_emission_type = fields.Selection(
        selection=[("1", "Normal")],
        string="SRI Emission Type",
        default="1",
    )
    in_edi_obligado_contabilidad = fields.Boolean(
        string="Required to Keep Accounting",
        default=True,
        help="Maps to the 'obligadoContabilidad' (SI/NO) field of the XML.",
    )
    in_edi_contribuyente_especial = fields.Char(
        string="Special Taxpayer Resolution",
        help="Resolution number if the company is a 'contribuyente especial'. "
        "Leave empty otherwise.",
    )
    in_edi_razon_social = fields.Char(
        string="Legal Name (Razón Social)",
        help="'razonSocial' sent to the SRI. Must match the name registered for "
        "the RUC. Defaults to the company name when left empty.",
    )
    in_edi_nombre_comercial = fields.Char(string="Commercial Name")
    in_edi_dir_matriz = fields.Char(
        string="Head Office Address",
        help="'dirMatriz' sent to the SRI. Defaults to the company street.",
    )
