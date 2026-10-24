"""AES-GCM for TikTok tokens at rest. Ciphertext layout: base64(nonce[12] || ct+tag)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


class CryptoError(Exception):
    pass


def _key(raw: str | None = None) -> bytes:
    raw = raw if raw is not None else get_settings().token_enc_key
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError as e:
        raise CryptoError("TOKEN_ENC_KEY is not valid base64") from e
    if len(key) != 32:
        raise CryptoError("TOKEN_ENC_KEY must decode to 32 bytes")
    return key


def encrypt(plaintext: str, key: str | None = None) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key(key)).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str, key: str | None = None) -> str:
    blob = base64.b64decode(token)
    return AESGCM(_key(key)).decrypt(blob[:12], blob[12:], None).decode()
