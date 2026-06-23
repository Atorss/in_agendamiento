import base64
import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class InEdiCertificate(models.Model):
    """Company-scoped electronic signature certificate (.p12) for the SRI.

    Unlike the per-employee certificate used to sign clinical documents, the
    SRI signs invoices with the *issuing company's* certificate (the one bound
    to the company RUC). The private-key password is stored encrypted with a
    Fernet key derived from the database UUID, and the raw password never
    touches a stored field (it is supplied through the validation wizard).
    """

    _name = "in_edi.certificate"
    _description = "SRI Electronic Signature Certificate"
    _check_company_auto = True
    _order = "state asc, date_end desc"

    name = fields.Char(string="Name", required=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    p12_file = fields.Binary(
        string="P12 File",
        required=True,
        attachment=True,
        help="PKCS#12 certificate file (.p12) issued to the company RUC.",
    )
    p12_filename = fields.Char(string="P12 Filename")
    password_encrypted = fields.Char(
        string="Encrypted Password",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )

    # Metadata extracted from the certificate on validation.
    subject_cn = fields.Char(string="Subject", readonly=True)
    issuer = fields.Char(string="Issued By", readonly=True)
    date_start = fields.Date(string="Valid From", readonly=True)
    date_end = fields.Date(string="Valid Until", readonly=True)
    is_expired = fields.Boolean(
        string="Expired", compute="_compute_is_expired", store=True
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ],
        string="Status",
        default="draft",
        copy=False,
    )
    notes = fields.Text(string="Notes")

    last_use = fields.Datetime(string="Last Use", readonly=True)
    use_count = fields.Integer(string="Use Count", default=0, readonly=True)

    @api.depends("date_end")
    def _compute_is_expired(self):
        today = fields.Date.today()
        for cert in self:
            cert.is_expired = bool(cert.date_end and cert.date_end < today)

    @api.constrains("state", "company_id")
    def _check_unique_active(self):
        for cert in self.filtered(lambda c: c.state == "active"):
            other = self.search(
                [
                    ("company_id", "=", cert.company_id.id),
                    ("state", "=", "active"),
                    ("id", "!=", cert.id),
                ],
                limit=1,
            )
            if other:
                raise UserError(
                    _(
                        "Company %(company)s already has an active certificate: "
                        "%(name)s. Revoke or deactivate it first.",
                        company=cert.company_id.display_name,
                        name=other.name,
                    )
                )

    # ── Lifecycle actions ──

    def action_open_validate_wizard(self):
        self.ensure_one()
        if not self.p12_file:
            raise UserError(_("Upload a .p12 file before validating."))
        return {
            "name": _("Validate Certificate"),
            "type": "ir.actions.act_window",
            "res_model": "in_edi.certificate.validate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_certificate_id": self.id},
        }

    def action_set_active(self):
        for cert in self:
            if not cert.date_end:
                raise UserError(_("Validate the certificate before activating it."))
            if cert.is_expired:
                raise UserError(_("Cannot activate an expired certificate."))
            cert.search(
                [
                    ("company_id", "=", cert.company_id.id),
                    ("state", "=", "active"),
                    ("id", "!=", cert.id),
                ]
            ).write({"state": "draft"})
            cert.state = "active"

    def action_set_revoked(self):
        self.write({"state": "revoked"})

    def action_set_draft(self):
        for cert in self:
            if cert.state == "revoked":
                raise UserError(_("A revoked certificate cannot be reactivated."))
            cert.state = "draft"

    @api.model
    def _cron_check_expiration(self):
        expired = self.search(
            [("date_end", "<", fields.Date.today()), ("state", "=", "active")]
        )
        expired.write({"state": "expired"})
        return True

    def register_usage(self):
        self.ensure_one()
        self.write(
            {"last_use": fields.Datetime.now(), "use_count": self.use_count + 1}
        )

    # ── Crypto helpers ──

    def _get_fernet(self):
        """Return a Fernet cipher derived from a server-side master secret.

        The master secret MUST live outside the database (odoo.conf key
        ``in_edi_master_key`` or env var ``IN_EDI_MASTER_KEY``) so a database
        dump alone cannot decrypt the .p12 passwords — critical in a shared
        multi-tenant database where ``database.uuid`` is common to all tenants.
        The per-record salt mixes in the company id so tenants do not share key
        material. ``database.uuid`` is only an extra salt, never the secret.
        """
        import os

        from cryptography.fernet import Fernet
        from odoo.tools import config

        secret = config.get("in_edi_master_key") or os.environ.get(
            "IN_EDI_MASTER_KEY"
        )
        if not secret:
            _logger.warning(
                "in_edi_master_key is not configured; falling back to an "
                "in-database secret. This is INSECURE for production: set "
                "'in_edi_master_key' in odoo.conf or IN_EDI_MASTER_KEY in the "
                "environment."
            )
            secret = (
                self.env["ir.config_parameter"].sudo().get_param("database.uuid")
                or "in_edi_dev"
            )
        db_uuid = (
            self.env["ir.config_parameter"].sudo().get_param("database.uuid") or ""
        )
        material = "%s:%s:%s" % (secret, db_uuid, self.company_id.id or 0)
        key_material = hashlib.sha256(material.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key_material))

    def encrypt_password(self, password):
        return self._get_fernet().encrypt(password.encode("utf-8")).decode("utf-8")

    def _decrypt_password(self):
        self.ensure_one()
        encrypted = self.sudo().password_encrypted
        if not encrypted:
            raise UserError(_("No password stored for this certificate."))
        return self._get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")

    def load_key_and_cert(self):
        """Load the private key and X509 certificate from the .p12.

        Uses the modern ``cryptography`` PKCS#12 loader (the pyOpenSSL
        ``load_pkcs12`` API is deprecated). Returns a tuple
        ``(private_key, certificate, additional_certs)``.
        """
        self.ensure_one()
        from cryptography.hazmat.primitives.serialization import pkcs12

        if not self.p12_file:
            raise UserError(_("This certificate has no .p12 file."))
        password = self._decrypt_password().encode("utf-8")
        p12_bytes = base64.b64decode(self.p12_file)
        try:
            key, cert, additional = pkcs12.load_key_and_certificates(
                p12_bytes, password
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a user error
            _logger.warning("Failed to load P12 for certificate %s: %s", self.id, exc)
            raise UserError(
                _("Could not open the .p12. Wrong password or invalid file.")
            ) from exc
        if key is None or cert is None:
            raise UserError(_("The .p12 does not contain a key/certificate pair."))
        return key, cert, additional or []

    @api.model
    def get_active_certificate(self, company):
        """Return the active certificate for ``company`` or raise.

        The search is intentionally NOT sudo so the per-company record rule is
        enforced: a user can only ever reach their own company's signing key.
        Reading the encrypted password still elevates, but only for that field
        (see ``_decrypt_password``).
        """
        cert = self.search(
            [("company_id", "=", company.id), ("state", "=", "active")], limit=1
        )
        if not cert:
            raise UserError(
                _(
                    "Company %s has no active SRI signing certificate.",
                    company.display_name,
                )
            )
        return cert
