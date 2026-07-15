# -*- coding: utf-8 -*-
"""Criptografía del Data Endpoint de WhatsApp Flows (protocolo Meta).

Requests: clave AES-GCM (tag 128 bits anexado) envuelta con RSA-OAEP
SHA-256. Respuestas: misma AES con el IV invertido bit a bit, en base64.
Spec §3.3; docs: developers.facebook.com/docs/whatsapp/flows/guides/
implementingyourflowendpoint/
"""
import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_keypair_pem():
    """Par RSA-2048. Devuelve (private_pem, public_pem) como str PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv.decode(), pub.decode()


def decrypt_request(body, private_key_pem):
    """Descifra un request del endpoint. Lanza ValueError si no puede
    (el controller lo traduce a HTTP 421, como exige Meta)."""
    try:
        key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None)
        aes_key = key.decrypt(
            base64.b64decode(body['encrypted_aes_key']),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                         algorithm=hashes.SHA256(), label=None))
        iv = base64.b64decode(body['initial_vector'])
        data = base64.b64decode(body['encrypted_flow_data'])
        clear = AESGCM(aes_key).decrypt(iv, data, None)
        return json.loads(clear.decode()), aes_key, iv
    except Exception as exc:
        raise ValueError('flow request undecryptable') from exc


def encrypt_response(payload, aes_key, iv):
    """Cifra la respuesta con el IV invertido bit a bit. Devuelve base64."""
    flipped = bytes(b ^ 0xFF for b in iv)
    ct = AESGCM(aes_key).encrypt(flipped, json.dumps(payload).encode(), None)
    return base64.b64encode(ct).decode()
