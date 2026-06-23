import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# SRI offline web services (WSDL). Test = celcer, Production = cel.
SRI_ENDPOINTS = {
    "1": {  # test / certification
        "reception": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
        "RecepcionComprobantesOffline?wsdl",
        "authorization": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
        "AutorizacionComprobantesOffline?wsdl",
    },
    "2": {  # production
        "reception": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/"
        "RecepcionComprobantesOffline?wsdl",
        "authorization": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/"
        "AutorizacionComprobantesOffline?wsdl",
    },
}

SOAP_TIMEOUT = 40  # seconds


class InEdiDocument(models.Model):
    """One electronic-document emission against the SRI for an invoice.

    Holds the generated and signed XML, the access key, and the lifecycle of
    the SRI exchange (reception -> authorization).
    """

    _name = "in_edi.document"
    _description = "SRI Electronic Document"
    _order = "create_date desc"
    _rec_name = "access_key"
    _check_company_auto = True

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        related="move_id.company_id", store=True, index=True
    )
    access_key = fields.Char(string="Access Key", size=49, copy=False, index=True)
    sequential = fields.Char(string="Sequential", size=9, copy=False)
    environment = fields.Selection(
        selection=[("1", "Test"), ("2", "Production")], string="Environment"
    )
    xml_file = fields.Binary(string="XML", attachment=True, copy=False)
    xml_filename = fields.Char(string="XML Filename")
    xml_signed_file = fields.Binary(
        string="Signed XML", attachment=True, copy=False
    )
    xml_signed_filename = fields.Char(string="Signed XML Filename")
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("signed", "Signed"),
            ("sent", "Sent (received)"),
            ("returned", "Returned (DEVUELTA)"),
            ("authorized", "Authorized"),
            ("rejected", "Rejected"),
        ],
        string="EDI Status",
        default="draft",
        copy=False,
        index=True,
    )
    authorization_number = fields.Char(string="Authorization Number", copy=False)
    authorization_date = fields.Datetime(string="Authorization Date", copy=False)
    sri_messages = fields.Text(string="SRI Messages", copy=False)

    # ── Signing ──

    def _sign(self, company):
        """Sign the stored XML with the company's active certificate."""
        self.ensure_one()
        if not self.xml_file:
            raise UserError(_("There is no XML to sign."))
        from ..utils import xades

        certificate = self.env["in_edi.certificate"].get_active_certificate(company)
        key, cert, _additional = certificate.load_key_and_cert()
        signed = xades.sign_xml_sri(base64.b64decode(self.xml_file), key, cert)
        self.write(
            {
                "xml_signed_file": base64.b64encode(signed),
                "xml_signed_filename": "%s_signed.xml"
                % (self.access_key or "comprobante"),
                "state": "signed",
            }
        )
        certificate.register_usage()

    def _send_to_sri_full(self):
        """Reception then authorization in one shot."""
        self.ensure_one()
        if self.state not in ("signed", "sent", "returned"):
            raise UserError(_("Sign the document before sending it."))
        self._send_reception()
        if self.state == "sent":
            self._query_authorization()
        return True

    @api.model
    def _cron_query_pending_authorizations(self):
        """Re-query authorization for documents the SRI received but has not
        authorized yet (the SRI authorization step is asynchronous)."""
        pending = self.search([("state", "=", "sent")], limit=200)
        for doc in pending:
            try:
                doc._query_authorization()
            except Exception:  # noqa: BLE001 - keep the cron resilient
                _logger.exception(
                    "Authorization polling failed for document %s", doc.id
                )
        return True

    # ── SOAP plumbing ──

    def _get_soap_client(self, service):
        """Return a zeep client for ``service`` ('reception'|'authorization')."""
        self.ensure_one()
        try:
            from zeep import Client
            from zeep.transports import Transport
        except ImportError as exc:  # pragma: no cover - env guard
            raise UserError(
                _("The 'zeep' Python library is required to reach the SRI.")
            ) from exc

        env = self.environment or self.company_id.in_edi_environment or "1"
        wsdl = SRI_ENDPOINTS[env][service]
        transport = Transport(timeout=SOAP_TIMEOUT, operation_timeout=SOAP_TIMEOUT)
        return Client(wsdl=wsdl, transport=transport)

    def action_send_to_sri(self):
        """Send to reception and, if received, query authorization."""
        for doc in self:
            if doc.state == "authorized":
                continue
            if not doc.xml_signed_file:
                raise UserError(_("Sign the document before sending it."))
            doc._send_reception()
            if doc.state == "sent":
                doc._query_authorization()
        return True

    def _send_reception(self):
        self.ensure_one()
        signed_xml = base64.b64decode(self.xml_signed_file)
        client = self._get_soap_client("reception")
        try:
            response = client.service.validarComprobante(xml=signed_xml)
        except Exception as exc:  # noqa: BLE001 - network/SOAP fault
            # Record the diagnosis and stop: raising here would roll back the
            # write and lose the message. State stays put so it can be retried.
            _logger.exception("SRI reception call failed")
            self.write({"sri_messages": _("Reception transport error: %s", exc)})
            return False

        estado = getattr(response, "estado", None)
        if estado == "RECIBIDA":
            self.write({"state": "sent", "sri_messages": _("RECIBIDA")})
        else:
            self.write(
                {
                    "state": "returned",
                    "sri_messages": self._format_reception_messages(response),
                }
            )

    def _query_authorization(self):
        self.ensure_one()
        client = self._get_soap_client("authorization")
        try:
            response = client.service.autorizacionComprobante(
                claveAccesoComprobante=self.access_key
            )
        except Exception as exc:  # noqa: BLE001 - network/SOAP fault
            _logger.exception("SRI authorization call failed")
            self.write({"sri_messages": _("Authorization transport error: %s", exc)})
            return False

        autorizaciones = getattr(response, "autorizaciones", None)
        items = getattr(autorizaciones, "autorizacion", []) if autorizaciones else []
        if not items:
            self.write({"sri_messages": _("No authorization returned yet (pending).")})
            return

        auth = items[0]
        estado = getattr(auth, "estado", None)
        if estado == "AUTORIZADO":
            comprobante = getattr(auth, "comprobante", None)
            vals = {
                "state": "authorized",
                "authorization_number": getattr(
                    auth, "numeroAutorizacion", self.access_key
                ),
                "sri_messages": _("AUTORIZADO"),
            }
            auth_date = getattr(auth, "fechaAutorizacion", None)
            if auth_date:
                vals["authorization_date"] = fields.Datetime.to_string(
                    auth_date.replace(tzinfo=None)
                    if hasattr(auth_date, "replace")
                    else auth_date
                )
            if comprobante:
                vals["xml_signed_file"] = base64.b64encode(
                    comprobante.encode("utf-8")
                    if isinstance(comprobante, str)
                    else comprobante
                )
            self.write(vals)
        else:
            self.write(
                {
                    "state": "rejected",
                    "sri_messages": self._format_authorization_messages(auth),
                }
            )

    @api.model
    def _format_reception_messages(self, response):
        lines = []
        comprobantes = getattr(response, "comprobantes", None)
        items = getattr(comprobantes, "comprobante", []) if comprobantes else []
        for comp in items:
            mensajes = getattr(comp, "mensajes", None)
            for msg in getattr(mensajes, "mensaje", []) if mensajes else []:
                lines.append(self._format_message(msg))
        return "\n".join(lines) or _("DEVUELTA (no detail provided).")

    @api.model
    def _format_authorization_messages(self, auth):
        lines = [_("NO AUTORIZADO")]
        mensajes = getattr(auth, "mensajes", None)
        for msg in getattr(mensajes, "mensaje", []) if mensajes else []:
            lines.append(self._format_message(msg))
        return "\n".join(lines)

    @api.model
    def _format_message(self, msg):
        return "[%s] %s — %s" % (
            getattr(msg, "identificador", ""),
            getattr(msg, "mensaje", ""),
            getattr(msg, "informacionAdicional", "") or "",
        )
