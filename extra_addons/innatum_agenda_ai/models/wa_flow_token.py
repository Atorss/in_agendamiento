# -*- coding: utf-8 -*-
"""flow_token firmado (HMAC) para WhatsApp Flows.

Correlaciona el Flow con la sesión (Meta NO devuelve el flow_id en la
respuesta) y evita tokens forjados/reciclados. Formato:
ft1:<session_id>:<expira_epoch>:<hmac_sha256_hex>."""
import hashlib
import hmac
import secrets

TTL_SECONDS = 48 * 3600
PARAM_SECRET = 'innatum_wa.flow_token_secret'


def _sign(base, secret):
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def make_flow_token(session_id, secret, now_ts):
    base = 'ft1:%d:%d' % (session_id, int(now_ts) + TTL_SECONDS)
    return '%s:%s' % (base, _sign(base, secret))


def check_flow_token(token, secret, now_ts):
    """session_id si el token es válido y vigente; None si no."""
    if not token:
        return None
    parts = str(token).split(':')
    if len(parts) != 4 or parts[0] != 'ft1':
        return None
    try:
        sid, exp = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    base = 'ft1:%d:%d' % (sid, exp)
    firma = parts[3]
    # Input no confiable: compare_digest lanza TypeError con no-ASCII.
    if len(firma) != 64 or any(c not in '0123456789abcdef' for c in firma):
        return None
    if not hmac.compare_digest(_sign(base, secret), firma):
        return None
    if exp <= now_ts:
        return None
    return sid


def get_flow_token_secret(env):
    icp = env['ir.config_parameter'].sudo()
    secret = icp.get_param(PARAM_SECRET)
    if not secret:
        secret = secrets.token_hex(32)
        icp.set_param(PARAM_SECRET, secret)
    return secret
