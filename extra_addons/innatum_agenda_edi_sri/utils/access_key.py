"""SRI access key (clave de acceso) generation and validation.

Pure, dependency-free helpers implementing the 49-digit access key defined in
the SRI "Ficha Técnica de Comprobantes Electrónicos" (offline scheme). Kept
free of any Odoo import so it can be unit-tested in isolation.

Layout of the 49 digits (Tabla 1 of the ficha técnica):

    | pos | field            | format    | length |
    |-----|------------------|-----------|--------|
    | 1   | issue date       | ddmmaaaa  | 8      |
    | 2   | document type    | 01..      | 2      |
    | 3   | issuer RUC       | numeric   | 13     |
    | 4   | environment      | 1=test    | 1      |
    | 5   | serie            | estab+ptoEmi | 6   |
    | 6   | sequential       | numeric   | 9      |
    | 7   | numeric code     | numeric   | 8      |
    | 8   | emission type    | 1=normal  | 1      |
    | 9   | check digit      | mod 11    | 1      |
"""

ENVIRONMENT_TEST = "1"
ENVIRONMENT_PROD = "2"
EMISSION_NORMAL = "1"

# Document types (Tabla 3). Only the ones we emit are listed here.
DOC_TYPE_INVOICE = "01"
DOC_TYPE_WITHHOLD = "07"
DOC_TYPE_CREDIT_NOTE = "04"
DOC_TYPE_DEBIT_NOTE = "05"
DOC_TYPE_DELIVERY_NOTE = "06"


def compute_check_digit(payload):
    """Return the module-11 check digit for the first 48 digits.

    Weights cycle 2..7 applied right-to-left. Special cases per the ficha:
    a remainder yielding 11 maps to 0 and 10 maps to 1.

    :param payload: string of 48 numeric characters.
    :returns: a single character ('0'..'9').
    """
    if not payload.isdigit():
        raise ValueError("Access key payload must be numeric.")
    if len(payload) != 48:
        raise ValueError(
            "Access key payload must be 48 digits, got %d." % len(payload)
        )

    weights = (2, 3, 4, 5, 6, 7)
    total = 0
    for index, char in enumerate(reversed(payload)):
        weight = weights[index % len(weights)]
        total += int(char) * weight

    remainder = total % 11
    check = 11 - remainder
    if check == 11:
        check = 0
    elif check == 10:
        check = 1
    return str(check)


def build_access_key(
    issue_date_ddmmyyyy,
    doc_type,
    ruc,
    environment,
    estab,
    pto_emi,
    sequential,
    numeric_code,
    emission_type=EMISSION_NORMAL,
):
    """Assemble the full 49-digit access key.

    All numeric components are validated and zero-padded to their fixed widths.

    :param issue_date_ddmmyyyy: 8-char string 'ddmmaaaa'.
    :param doc_type: 2-char document type code (e.g. '01').
    :param ruc: 13-char issuer RUC.
    :param environment: '1' (test) or '2' (production).
    :param estab: establishment code (3 digits).
    :param pto_emi: emission point code (3 digits).
    :param sequential: document sequential (up to 9 digits).
    :param numeric_code: 8-digit numeric code (issuer-defined).
    :param emission_type: '1' for normal emission.
    :returns: 49-char access key string.
    """
    if len(issue_date_ddmmyyyy) != 8 or not issue_date_ddmmyyyy.isdigit():
        raise ValueError("issue_date must be 8 digits 'ddmmaaaa'.")
    if doc_type not in {
        DOC_TYPE_INVOICE,
        DOC_TYPE_WITHHOLD,
        DOC_TYPE_CREDIT_NOTE,
        DOC_TYPE_DEBIT_NOTE,
        DOC_TYPE_DELIVERY_NOTE,
    }:
        raise ValueError("Unsupported document type: %s" % doc_type)
    if len(ruc) != 13 or not ruc.isdigit():
        raise ValueError("RUC must be 13 digits.")
    if environment not in {ENVIRONMENT_TEST, ENVIRONMENT_PROD}:
        raise ValueError("environment must be '1' or '2'.")

    serie = "%s%s" % (estab.zfill(3), pto_emi.zfill(3))
    if len(serie) != 6:
        raise ValueError("estab+ptoEmi must total 6 digits.")

    sequential = str(sequential).zfill(9)
    if len(sequential) != 9:
        raise ValueError("sequential must be at most 9 digits.")

    numeric_code = str(numeric_code).zfill(8)
    if len(numeric_code) != 8:
        raise ValueError("numeric_code must be at most 8 digits.")

    payload = "".join((
        issue_date_ddmmyyyy,
        doc_type,
        ruc,
        environment,
        serie,
        sequential,
        numeric_code,
        emission_type,
    ))
    if len(payload) != 48:
        raise ValueError(
            "Access key payload must be 48 digits, got %d." % len(payload)
        )

    return payload + compute_check_digit(payload)


def is_valid_access_key(access_key):
    """Validate length and check digit of a 49-digit access key."""
    if len(access_key) != 49 or not access_key.isdigit():
        return False
    return compute_check_digit(access_key[:48]) == access_key[48]
