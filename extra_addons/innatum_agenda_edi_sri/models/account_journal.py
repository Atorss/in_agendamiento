from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo import api


class AccountJournal(models.Model):
    _inherit = "account.journal"

    in_edi_enabled = fields.Boolean(
        string="Electronic Invoicing (SRI)",
        help="Documents posted from this journal are emitted electronically to "
        "the SRI.",
    )
    in_edi_estab = fields.Char(
        string="Establishment (estab)",
        size=3,
        help="3-digit establishment code assigned by the SRI (e.g. 001).",
    )
    in_edi_pto_emi = fields.Char(
        string="Emission Point (ptoEmi)",
        size=3,
        help="3-digit emission point code assigned by the SRI (e.g. 001).",
    )
    in_edi_sequence_next = fields.Integer(
        string="Next Sequential",
        default=1,
        help="Next 'secuencial' to allocate for this establishment/emission "
        "point. The SRI requires a continuous sequence per estab+ptoEmi.",
    )

    @api.constrains("in_edi_enabled", "in_edi_estab", "in_edi_pto_emi")
    def _check_edi_codes(self):
        for journal in self.filtered("in_edi_enabled"):
            for value, label in (
                (journal.in_edi_estab, _("Establishment")),
                (journal.in_edi_pto_emi, _("Emission Point")),
            ):
                if not value or not value.isdigit() or len(value) != 3:
                    raise ValidationError(
                        _("%s must be exactly 3 digits.", label)
                    )

    def _in_edi_allocate_sequential(self):
        """Reserve and return the next zero-padded 9-digit sequential.

        Uses a row-level ``FOR UPDATE`` lock so concurrent emissions (multiple
        users or crons in a multi-tenant SaaS) never read the same counter and
        produce duplicate access keys.
        """
        self.ensure_one()
        self.env.cr.execute(
            "SELECT in_edi_sequence_next FROM account_journal "
            "WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        row = self.env.cr.fetchone()
        current = (row[0] if row and row[0] else None) or 1
        self.env.cr.execute(
            "UPDATE account_journal SET in_edi_sequence_next = %s WHERE id = %s",
            (current + 1, self.id),
        )
        self.invalidate_recordset(["in_edi_sequence_next"])
        return str(current).zfill(9)
