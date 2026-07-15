# -*- coding: utf-8 -*-
"""Simulación del lado Meta para tests del Data Endpoint de Flows:
cifra requests como lo hace WhatsApp y descifra respuestas (IV invertido).
Vive en tests/ a propósito: producción nunca cifra requests."""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def meta_encrypt_request(payload, public_key_pem):
    """Devuelve (body_dict, aes_key, iv) como los enviaría Meta."""
    aes_key = os.urandom(16)
    iv = os.urandom(12)
    pub = serialization.load_pem_public_key(public_key_pem.encode())
    enc_key = pub.encrypt(aes_key, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(), label=None))
    ct = AESGCM(aes_key).encrypt(iv, json.dumps(payload).encode(), None)
    return ({
        'encrypted_flow_data': base64.b64encode(ct).decode(),
        'encrypted_aes_key': base64.b64encode(enc_key).decode(),
        'initial_vector': base64.b64encode(iv).decode(),
    }, aes_key, iv)


def meta_decrypt_response(b64, aes_key, iv):
    flipped = bytes(b ^ 0xFF for b in iv)
    clear = AESGCM(aes_key).decrypt(flipped, base64.b64decode(b64), None)
    return json.loads(clear.decode())
