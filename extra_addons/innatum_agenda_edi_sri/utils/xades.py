"""XAdES-BES enveloped signature for SRI electronic documents.

Implemented from scratch following the signature profile that the SRI
validates against (the de-facto structure produced by the official FirmaEC /
MITyC applet), using ``cryptography`` (permissive license) and ``lxml`` only —
no AGPL/proprietary dependency.

Profile summary (Ficha Técnica, section 6):

* XAdES-BES, ETSI 1.3.2.
* Enveloped signature (the ``ds:Signature`` is the last child of the root).
* SignatureMethod RSA-SHA1, inclusive C14N (REC-xml-c14n-20010315), 2048-bit.
* Three references, in this order:
    1. ``#...-SignedProperties`` (Type SignedProperties)
    2. ``#Certificate...`` (the KeyInfo element)
    3. ``#comprobante`` (the document root, with enveloped transform)
* ``KeyInfo`` carries the signer X509 certificate (base64) and RSAKeyValue,
  and is itself signed (reference 2).

.. important::
   Byte-exact canonicalization is what makes the SRI accept the signature.
   Digests are computed on the nodes *in their final tree position* so the
   inherited namespace context matches what the SRI verifier reconstructs.
   This signer must be validated end-to-end against the SRI test environment
   with a real .p12 before going to production.
"""

import base64
import hashlib
import random
from datetime import datetime

from lxml import etree

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
ETSI_NS = "http://uri.etsi.org/01903/v1.3.2#"

_C14N_ALG = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_SIG_ALG = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
_SHA1_ALG = "http://www.w3.org/2000/09/xmldsig#sha1"
_ENVELOPED_ALG = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
_SIGNED_PROPS_TYPE = "http://uri.etsi.org/01903#SignedProperties"

NSMAP = {"ds": DS_NS, "etsi": ETSI_NS}


def _ds(tag):
    return "{%s}%s" % (DS_NS, tag)


def _etsi(tag):
    return "{%s}%s" % (ETSI_NS, tag)


def _rand():
    """Return a positive integer used to build unique element ids."""
    return random.randint(100000, 999999)


def _c14n(node):
    """Inclusive canonicalization (C14N 1.0) of a node, in its tree context."""
    return etree.tostring(node, method="c14n", exclusive=False, with_comments=False)


def _sha1_b64(data):
    return base64.b64encode(hashlib.sha1(data).digest()).decode("ascii")


def _int_to_b64(value):
    """Base64 of a positive integer's big-endian byte representation."""
    length = (value.bit_length() + 7) // 8
    return base64.b64encode(value.to_bytes(length, "big")).decode("ascii")


def _cert_to_b64(certificate):
    """Return the certificate DER bytes encoded in base64 (single line)."""
    from cryptography.hazmat.primitives.serialization import Encoding

    return base64.b64encode(certificate.public_bytes(Encoding.DER)).decode("ascii")


def sign_xml_sri(xml_bytes, private_key, certificate):
    """Sign ``xml_bytes`` and return the signed document as bytes.

    :param xml_bytes: the unsigned comprobante XML. Its root element must carry
        ``id="comprobante"``.
    :param private_key: an RSA private key (``cryptography`` object).
    :param certificate: the matching X509 certificate (``cryptography`` object).
    :returns: signed XML bytes, UTF-8, with XML declaration.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(xml_bytes, parser=parser)
    if root.get("id") != "comprobante":
        root.set("id", "comprobante")

    # ── Unique ids (FirmaEC-style) ──
    n = _rand()
    sig_id = "Signature%s" % n
    sig_sv_id = "SignatureValue%s" % _rand()
    cert_id = "Certificate%s" % n
    signed_props_id = "%s-SignedProperties%s" % (sig_id, _rand())
    signed_info_id = "Signature-SignedInfo%s" % _rand()
    ref_doc_id = "Reference-ID-%s" % _rand()
    signed_props_ref_id = "SignedPropertiesID%s" % _rand()
    object_id = "%s-Object%s" % (sig_id, _rand())

    # ── 1. Digest of the document root (enveloped) computed before attaching
    #        the signature: identical to removing ds:Signature then C14N. ──
    doc_digest = _sha1_b64(_c14n(root))

    # ── 2. Build the ds:Signature subtree (digests filled later) ──
    signature = etree.SubElement(root, _ds("Signature"), nsmap=NSMAP)
    signature.set("Id", sig_id)

    signed_info = etree.SubElement(signature, _ds("SignedInfo"))
    signed_info.set("Id", signed_info_id)
    etree.SubElement(signed_info, _ds("CanonicalizationMethod"), Algorithm=_C14N_ALG)
    etree.SubElement(signed_info, _ds("SignatureMethod"), Algorithm=_SIG_ALG)

    # Reference 1 -> SignedProperties
    ref_sp = etree.SubElement(
        signed_info,
        _ds("Reference"),
        Id=signed_props_ref_id,
        Type=_SIGNED_PROPS_TYPE,
        URI="#%s" % signed_props_id,
    )
    etree.SubElement(ref_sp, _ds("DigestMethod"), Algorithm=_SHA1_ALG)
    ref_sp_digest = etree.SubElement(ref_sp, _ds("DigestValue"))

    # Reference 2 -> KeyInfo (the certificate)
    ref_cert = etree.SubElement(signed_info, _ds("Reference"), URI="#%s" % cert_id)
    etree.SubElement(ref_cert, _ds("DigestMethod"), Algorithm=_SHA1_ALG)
    ref_cert_digest = etree.SubElement(ref_cert, _ds("DigestValue"))

    # Reference 3 -> the document (#comprobante), enveloped
    ref_doc = etree.SubElement(
        signed_info, _ds("Reference"), Id=ref_doc_id, URI="#comprobante"
    )
    transforms = etree.SubElement(ref_doc, _ds("Transforms"))
    etree.SubElement(transforms, _ds("Transform"), Algorithm=_ENVELOPED_ALG)
    etree.SubElement(ref_doc, _ds("DigestMethod"), Algorithm=_SHA1_ALG)
    ref_doc_digest = etree.SubElement(ref_doc, _ds("DigestValue"))
    ref_doc_digest.text = doc_digest

    signature_value = etree.SubElement(signature, _ds("SignatureValue"), Id=sig_sv_id)

    # ── KeyInfo (Reference 2 target) ──
    key_info = etree.SubElement(signature, _ds("KeyInfo"), Id=cert_id)
    x509_data = etree.SubElement(key_info, _ds("X509Data"))
    x509_cert = etree.SubElement(x509_data, _ds("X509Certificate"))
    x509_cert.text = _cert_to_b64(certificate)

    public_numbers = certificate.public_key().public_numbers()
    key_value = etree.SubElement(key_info, _ds("KeyValue"))
    rsa_key_value = etree.SubElement(key_value, _ds("RSAKeyValue"))
    etree.SubElement(rsa_key_value, _ds("Modulus")).text = _int_to_b64(
        public_numbers.n
    )
    etree.SubElement(rsa_key_value, _ds("Exponent")).text = _int_to_b64(
        public_numbers.e
    )

    # ── Object / QualifyingProperties / SignedProperties (Reference 1 target) ──
    obj = etree.SubElement(signature, _ds("Object"), Id=object_id)
    qualifying = etree.SubElement(
        obj, _etsi("QualifyingProperties"), Target="#%s" % sig_id
    )
    signed_props = etree.SubElement(
        qualifying, _etsi("SignedProperties"), Id=signed_props_id
    )
    signed_sig_props = etree.SubElement(
        signed_props, _etsi("SignedSignatureProperties")
    )
    etree.SubElement(signed_sig_props, _etsi("SigningTime")).text = (
        datetime.now().replace(microsecond=0).isoformat()
    )

    signing_cert = etree.SubElement(signed_sig_props, _etsi("SigningCertificate"))
    cert_node = etree.SubElement(signing_cert, _etsi("Cert"))
    cert_digest = etree.SubElement(cert_node, _etsi("CertDigest"))
    etree.SubElement(cert_digest, _ds("DigestMethod"), Algorithm=_SHA1_ALG)
    from cryptography.hazmat.primitives.serialization import Encoding

    cert_der = certificate.public_bytes(Encoding.DER)
    etree.SubElement(cert_digest, _ds("DigestValue")).text = _sha1_b64(cert_der)
    issuer_serial = etree.SubElement(cert_node, _etsi("IssuerSerial"))
    etree.SubElement(issuer_serial, _ds("X509IssuerName")).text = (
        certificate.issuer.rfc4514_string()
    )
    etree.SubElement(issuer_serial, _ds("X509SerialNumber")).text = str(
        certificate.serial_number
    )

    signed_data_props = etree.SubElement(
        signed_props, _etsi("SignedDataObjectProperties")
    )
    data_object_format = etree.SubElement(
        signed_data_props,
        _etsi("DataObjectFormat"),
        ObjectReference="#%s" % ref_doc_id,
    )
    etree.SubElement(data_object_format, _etsi("Description")).text = (
        "contenido comprobante"
    )
    etree.SubElement(data_object_format, _etsi("MimeType")).text = "text/xml"

    # ── 3. Fill the remaining digests, computed in-tree for correct ns context ──
    ref_cert_digest.text = _sha1_b64(_c14n(key_info))
    ref_sp_digest.text = _sha1_b64(_c14n(signed_props))

    # ── 4. Sign the canonicalized SignedInfo ──
    signature_value.text = base64.b64encode(
        private_key.sign(_c14n(signed_info), padding.PKCS1v15(), hashes.SHA1())
    ).decode("ascii")

    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
