import base64
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class InEdiCertificateValidateWizard(models.TransientModel):
    """Validate a .p12, extract its metadata and store the password encrypted.

    The raw password lives only in this transient record for the duration of
    the action; it is encrypted onto the certificate and never persisted in
    clear text.
    """

    _name = "in_edi.certificate.validate.wizard"
    _description = "Validate SRI Certificate"

    certificate_id = fields.Many2one(
        comodel_name="in_edi.certificate",
        string="Certificate",
        required=True,
    )
    password = fields.Char(string="Password", required=True)

    def _format_x509_name(self, name, preferred_oids):
        """Return the first available attribute value from an x509 Name."""
        for oid in preferred_oids:
            attributes = name.get_attributes_for_oid(oid)
            if attributes:
                return attributes[0].value
        return ""

    def action_validate(self):
        self.ensure_one()
        certificate = self.certificate_id
        if not certificate.p12_file:
            raise UserError(_("The certificate has no .p12 file attached."))

        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.x509.oid import NameOID

        p12_bytes = base64.b64decode(certificate.p12_file)
        try:
            key, cert, _additional = pkcs12.load_key_and_certificates(
                p12_bytes, self.password.encode("utf-8")
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as user error
            _logger.warning("P12 validation failed: %s", exc)
            raise UserError(
                _("Wrong password or invalid .p12 file.")
            ) from exc
        if key is None or cert is None:
            raise UserError(_("The .p12 does not contain a key/certificate pair."))

        subject_cn = self._format_x509_name(
            cert.subject, (NameOID.COMMON_NAME, NameOID.GIVEN_NAME)
        )
        issuer = self._format_x509_name(
            cert.issuer, (NameOID.COMMON_NAME, NameOID.ORGANIZATION_NAME)
        )

        certificate.sudo().write(
            {
                "subject_cn": subject_cn or _("Unknown holder"),
                "issuer": issuer or _("Unknown issuer"),
                "date_start": cert.not_valid_before.date(),
                "date_end": cert.not_valid_after.date(),
                "password_encrypted": certificate.encrypt_password(self.password),
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Certificate validated"),
                "message": _(
                    "Holder: %(holder)s | Issuer: %(issuer)s | Expires: %(end)s",
                    holder=subject_cn,
                    issuer=issuer,
                    end=cert.not_valid_after.date(),
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
