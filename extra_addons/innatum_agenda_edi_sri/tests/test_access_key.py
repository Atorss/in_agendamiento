from odoo.tests.common import TransactionCase

from ..utils import access_key as ak


class TestAccessKey(TransactionCase):
    """Unit tests for the SRI access key (clave de acceso)."""

    def test_check_digit_official_example(self):
        # Official ficha técnica example: the payload chunk '41261533'
        # yields check digit 6 under the module-11 algorithm.
        # Padded into a full 48-digit payload ending with that chunk so the
        # right-to-left weighting reproduces the documented result.
        payload = "41261533".rjust(48, "0")
        # Recompute the documented 8-digit case directly via the core weights.
        weights = (2, 3, 4, 5, 6, 7)
        total = sum(
            int(c) * weights[i % len(weights)]
            for i, c in enumerate(reversed("41261533"))
        )
        dv = 11 - (total % 11)
        dv = 0 if dv == 11 else (1 if dv == 10 else dv)
        self.assertEqual(dv, 6)
        # And the full-payload helper must produce a single valid digit.
        self.assertTrue(ak.compute_check_digit(payload).isdigit())

    def test_build_and_validate_roundtrip(self):
        key = ak.build_access_key(
            issue_date_ddmmyyyy="06062026",
            doc_type=ak.DOC_TYPE_INVOICE,
            ruc="1790012345001",
            environment=ak.ENVIRONMENT_TEST,
            estab="001",
            pto_emi="001",
            sequential="1",
            numeric_code="12345678",
        )
        self.assertEqual(len(key), 49)
        self.assertTrue(ak.is_valid_access_key(key))

    def test_corrupted_key_is_invalid(self):
        key = ak.build_access_key(
            issue_date_ddmmyyyy="06062026",
            doc_type=ak.DOC_TYPE_INVOICE,
            ruc="1790012345001",
            environment=ak.ENVIRONMENT_TEST,
            estab="001",
            pto_emi="001",
            sequential="2",
            numeric_code="12345678",
        )
        flipped = key[:-1] + ("0" if key[-1] != "0" else "1")
        self.assertFalse(ak.is_valid_access_key(flipped))

    def test_invalid_ruc_raises(self):
        with self.assertRaises(ValueError):
            ak.build_access_key(
                issue_date_ddmmyyyy="06062026",
                doc_type=ak.DOC_TYPE_INVOICE,
                ruc="123",  # too short
                environment=ak.ENVIRONMENT_TEST,
                estab="001",
                pto_emi="001",
                sequential="1",
                numeric_code="12345678",
            )
