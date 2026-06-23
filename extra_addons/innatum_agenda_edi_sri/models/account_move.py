import base64
import logging

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils import access_key as ak

_logger = logging.getLogger(__name__)

# IVA tax code (Tabla 16) and rate -> codigoPorcentaje (Tabla 18) mapping.
IVA_TAX_CODE = "2"
IVA_RATE_TO_CODE = {
    0.0: "0",
    5.0: "5",
    12.0: "2",
    13.0: "10",
    14.0: "3",
    15.0: "4",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    in_edi_document_ids = fields.One2many(
        comodel_name="in_edi.document",
        inverse_name="move_id",
        string="SRI Documents",
        copy=False,
    )
    in_edi_access_key = fields.Char(
        string="Access Key",
        compute="_compute_in_edi_fields",
        store=True,
        copy=False,
    )
    in_edi_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("signed", "Signed"),
            ("sent", "Sent (received)"),
            ("returned", "Returned (DEVUELTA)"),
            ("authorized", "Authorized"),
            ("rejected", "Rejected"),
        ],
        string="SRI Status",
        compute="_compute_in_edi_fields",
        store=True,
        copy=False,
    )

    @api.depends("in_edi_document_ids.state", "in_edi_document_ids.access_key")
    def _compute_in_edi_fields(self):
        for move in self:
            doc = move.in_edi_document_ids.sorted("create_date", reverse=True)[:1]
            move.in_edi_access_key = doc.access_key or False
            move.in_edi_state = doc.state or False

    # ── Public action ──

    def action_in_edi_send(self):
        """Generate, sign and send the electronic invoice to the SRI."""
        for move in self:
            move._in_edi_check_subscription()
            move._in_edi_check_ready()
            document = move._in_edi_get_or_create_document()
            document._send_to_sri_full()
        return True

    def _in_edi_check_subscription(self):
        """Gate por suscripción SaaS (Innatum).

        Guarda suave: solo aplica cuando el modelo de suscripción está
        presente (contexto SaaS de agendamiento). Si no, el módulo opera
        como facturación electrónica genérica — así sigue siendo usable en
        otros proyectos sin el SaaS, activándose/desactivándose por
        addons_path según el proyecto.
        """
        self.ensure_one()
        if 'in_agenda.suscripcion' not in self.env:
            return
        Sus = self.env['in_agenda.suscripcion'].sudo()
        if not Sus._company_has_feature(self.company_id, 'facturacion_sri'):
            raise UserError(_(
                "El plan de la empresa «%s» no incluye facturación electrónica "
                "al SRI. Contacta a Innatum para habilitarla.",
                self.company_id.name,
            ))

    def _in_edi_check_ready(self):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(_("Only customer invoices can be sent to the SRI."))
        if self.state != "posted":
            raise UserError(_("Post the invoice before sending it to the SRI."))
        if not self.journal_id.in_edi_enabled:
            raise UserError(
                _("Journal %s is not enabled for SRI electronic invoicing.",
                  self.journal_id.display_name)
            )
        if not self.company_id.vat:
            raise UserError(_("The company has no RUC (VAT) configured."))

    def _in_edi_get_or_create_document(self):
        self.ensure_one()
        document = self.in_edi_document_ids.filtered(
            lambda d: d.state != "authorized"
        ).sorted("create_date", reverse=True)[:1]
        if not document:
            document = self.env["in_edi.document"].create(
                {"move_id": self.id, "environment": self.company_id.in_edi_environment}
            )
        if document.state == "draft":
            # Allocate the access key + sequential exactly once per document so
            # retries never burn a new number (the SRI requires a gap-free
            # sequence per estab+ptoEmi).
            if not document.access_key:
                access_key, sequential = self._in_edi_build_access_key()
                document.write({"access_key": access_key, "sequential": sequential})
            xml_bytes = self._in_edi_build_invoice_xml(document)
            document.write(
                {
                    "xml_file": base64.b64encode(xml_bytes),
                    "xml_filename": "%s.xml" % document.access_key,
                }
            )
            document._sign(self.company_id)
        return document

    # ── RIDE helpers ──

    def _in_edi_barcode_src(self):
        """Code128 barcode of the access key as an embedded data-URI.

        Embedding the PNG avoids wkhtmltopdf having to fetch /report/barcode/
        over HTTP, which fails when the report worker cannot reach web.base.url.
        """
        self.ensure_one()
        if not self.in_edi_access_key:
            return ""
        png = self.env["ir.actions.report"].barcode(
            "Code128", self.in_edi_access_key,
            width=600, height=100, humanreadable=0,
        )
        return "data:image/png;base64,%s" % base64.b64encode(png).decode()

    # ── Access key ──

    def _in_edi_build_access_key(self):
        self.ensure_one()
        journal = self.journal_id
        sequential = journal._in_edi_allocate_sequential()
        numeric_code = str(self.id % 100000000).zfill(8)
        invoice_date = self.invoice_date or fields.Date.context_today(self)
        key = ak.build_access_key(
            issue_date_ddmmyyyy=invoice_date.strftime("%d%m%Y"),
            doc_type=ak.DOC_TYPE_INVOICE,
            ruc=self.company_id.vat,
            environment=self.company_id.in_edi_environment or "1",
            estab=journal.in_edi_estab,
            pto_emi=journal.in_edi_pto_emi,
            sequential=sequential,
            numeric_code=numeric_code,
            emission_type=self.company_id.in_edi_emission_type or "1",
        )
        if not ak.is_valid_access_key(key):
            raise UserError(_("Generated access key failed its check digit."))
        return key, sequential

    # ── XML builder (factura 1.1.0) ──

    def _in_edi_build_invoice_xml(self, document):
        self.ensure_one()
        company = self.company_id
        journal = self.journal_id
        access_key = document.access_key
        sequential = document.sequential
        if not access_key or not sequential:
            raise UserError(_("The document has no access key/sequential yet."))

        tax_groups = self._in_edi_tax_groups()
        total_tax = sum(group["valor"] for group in tax_groups)
        # importeTotal is derived from the same rounded values we send so that
        # the SRI invariant importeTotal == totalSinImpuestos + Σ valor holds.
        importe_total = self.currency_id.round(self.amount_untaxed + total_tax)

        factura = etree.Element("factura", id="comprobante", version="1.1.0")

        # infoTributaria
        info_trib = etree.SubElement(factura, "infoTributaria")
        self._add(info_trib, "ambiente", company.in_edi_environment or "1")
        self._add(info_trib, "tipoEmision", company.in_edi_emission_type or "1")
        self._add(info_trib, "razonSocial", company.in_edi_razon_social or company.name)
        if company.in_edi_nombre_comercial:
            self._add(info_trib, "nombreComercial", company.in_edi_nombre_comercial)
        self._add(info_trib, "ruc", company.vat)
        self._add(info_trib, "claveAcceso", access_key)
        self._add(info_trib, "codDoc", ak.DOC_TYPE_INVOICE)
        self._add(info_trib, "estab", journal.in_edi_estab)
        self._add(info_trib, "ptoEmi", journal.in_edi_pto_emi)
        self._add(info_trib, "secuencial", sequential)
        self._add(
            info_trib, "dirMatriz",
            company.in_edi_dir_matriz or company.street or "S/N",
        )

        # infoFactura
        info_fact = etree.SubElement(factura, "infoFactura")
        invoice_date = self.invoice_date or fields.Date.context_today(self)
        self._add(info_fact, "fechaEmision", invoice_date.strftime("%d/%m/%Y"))
        self._add(
            info_fact, "obligadoContabilidad",
            "SI" if company.in_edi_obligado_contabilidad else "NO",
        )
        if company.in_edi_contribuyente_especial:
            self._add(
                info_fact, "contribuyenteEspecial",
                company.in_edi_contribuyente_especial,
            )
        id_type, id_value = self._in_edi_partner_identification()
        self._add(info_fact, "tipoIdentificacionComprador", id_type)
        self._add(info_fact, "razonSocialComprador", self.partner_id.name or "")
        self._add(info_fact, "identificacionComprador", id_value)
        self._add(info_fact, "totalSinImpuestos", self._money(self.amount_untaxed))
        self._add(info_fact, "totalDescuento", self._money(self._total_discount()))

        # totalConImpuestos
        total_imp = etree.SubElement(info_fact, "totalConImpuestos")
        for group in tax_groups:
            ti = etree.SubElement(total_imp, "totalImpuesto")
            self._add(ti, "codigo", group["codigo"])
            self._add(ti, "codigoPorcentaje", group["codigo_porcentaje"])
            self._add(ti, "baseImponible", self._money(group["base"]))
            self._add(ti, "valor", self._money(group["valor"]))

        self._add(info_fact, "propina", self._money(0.0))
        self._add(info_fact, "importeTotal", self._money(importe_total))
        self._add(info_fact, "moneda", "DOLAR")

        pagos = etree.SubElement(info_fact, "pagos")
        pago = etree.SubElement(pagos, "pago")
        self._add(pago, "formaPago", "01")  # 01: sin sistema financiero (default)
        self._add(pago, "total", self._money(importe_total))

        # detalles
        detalles = etree.SubElement(factura, "detalles")
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            self._in_edi_add_detalle(detalles, line)

        # infoAdicional
        info_ad = etree.SubElement(factura, "infoAdicional")
        if self.partner_id.email:
            campo = etree.SubElement(info_ad, "campoAdicional", nombre="email")
            campo.text = self.partner_id.email
        campo = etree.SubElement(info_ad, "campoAdicional", nombre="Observacion")
        campo.text = self.ref or self.name or "-"

        return etree.tostring(factura, encoding="UTF-8", xml_declaration=True)

    # ── XML helpers (pure; no recordset state) ──

    @staticmethod
    def _add(parent, tag, value):
        node = etree.SubElement(parent, tag)
        node.text = "" if value is None else str(value)
        return node

    @staticmethod
    def _money(amount):
        return "%.2f" % (amount or 0.0)

    @staticmethod
    def _qty(amount):
        return "%.6f" % (amount or 0.0)

    @staticmethod
    def _iva_code_from_tax(tax):
        """Return the SRI codigoPorcentaje for an IVA tax (no silent default)."""
        return IVA_RATE_TO_CODE[round(tax.amount, 1)]

    def _in_edi_iva_taxes(self, line):
        """IVA taxes on a line: sale percentage taxes with a known SRI rate."""
        return line.tax_ids.filtered(
            lambda t: t.amount_type == "percent"
            and t.type_tax_use == "sale"
            and round(t.amount, 1) in IVA_RATE_TO_CODE
        )

    def _total_discount(self):
        self.ensure_one()
        total = 0.0
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            if line.discount:
                total += line.quantity * line.price_unit * (line.discount / 100.0)
        return self.currency_id.round(total)

    def _in_edi_partner_identification(self):
        """Return (tipoIdentificacion, identificacion) per Tabla 6."""
        self.ensure_one()
        partner = self.partner_id
        vat = (partner.vat or "").strip()
        if not vat:
            return "07", "9999999999999"  # consumidor final
        if len(vat) == 13:
            return "04", vat  # RUC
        if len(vat) == 10:
            return "05", vat  # cédula
        return "06", vat  # pasaporte / exterior

    def _in_edi_add_detalle(self, detalles, line):
        currency = self.currency_id
        detalle = etree.SubElement(detalles, "detalle")
        self._add(detalle, "codigoPrincipal", line.product_id.default_code or "0001")
        self._add(detalle, "descripcion", line.name or line.product_id.name or "-")
        self._add(detalle, "cantidad", self._qty(line.quantity))
        self._add(detalle, "precioUnitario", self._qty(line.price_unit))
        self._add(detalle, "descuento", self._money(
            currency.round(line.quantity * line.price_unit * (line.discount / 100.0))
        ))
        self._add(detalle, "precioTotalSinImpuesto", self._money(line.price_subtotal))

        impuestos = etree.SubElement(detalle, "impuestos")
        for tax in self._in_edi_iva_taxes(line):
            code = self._iva_code_from_tax(tax)
            valor = currency.round(line.price_subtotal * tax.amount / 100.0)
            impuesto = etree.SubElement(impuestos, "impuesto")
            self._add(impuesto, "codigo", IVA_TAX_CODE)
            self._add(impuesto, "codigoPorcentaje", code)
            self._add(impuesto, "tarifa", self._money(tax.amount))
            self._add(impuesto, "baseImponible", self._money(line.price_subtotal))
            self._add(impuesto, "valor", self._money(valor))

    def _in_edi_tax_groups(self):
        """Group invoice IVA taxes into totalImpuesto entries.

        ``valor`` is accumulated from per-line rounded values so the group total
        equals the sum of the detalle values (SRI cross-check) and feeds a
        consistent importeTotal.
        """
        self.ensure_one()
        currency = self.currency_id
        groups = {}
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            for tax in self._in_edi_iva_taxes(line):
                code = self._iva_code_from_tax(tax)
                valor = currency.round(line.price_subtotal * tax.amount / 100.0)
                bucket = groups.setdefault(
                    code,
                    {
                        "codigo": IVA_TAX_CODE,
                        "codigo_porcentaje": code,
                        "base": 0.0,
                        "valor": 0.0,
                    },
                )
                bucket["base"] = currency.round(bucket["base"] + line.price_subtotal)
                bucket["valor"] = currency.round(bucket["valor"] + valor)
        return list(groups.values())
