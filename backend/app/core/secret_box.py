"""Authenticated encryption for stored secrets (SMTP password).

AES-256-GCM with a random 96-bit nonce per encryption and associated data that
binds a ciphertext to its purpose, so it cannot be moved to another column.

Stored format: ``v1:<key_id>:<base64url(nonce || ciphertext+tag)>``, where
``key_id`` is the first 8 hex digits of SHA-256(key). It identifies which key
encrypted a value, so a rotation can tell old values from new ones.

Keys come only from configuration (environment / secret manager):
- ``EMAIL_SETTINGS_ENCRYPTION_KEY``: current key, used to encrypt and decrypt.
- ``EMAIL_SETTINGS_PREVIOUS_KEYS``: old keys, used to decrypt only.

There is no fallback and no auto-generated key. If the key is missing or
invalid, operations raise ``EncryptionKeyError`` with setup guidance.
"""

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_VERSION = "v1"
_NONCE_BYTES = 12

KEY_SETUP_HELP = (
    "Set EMAIL_SETTINGS_ENCRYPTION_KEY to a base64url-encoded 32-byte key, e.g. the output of: "
    'python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32))'
    '.decode())". Keep it in your secret store and back it up separately from the database.'
)


class EncryptionKeyError(RuntimeError):
    """The encryption key is missing or invalid."""


class DecryptionError(RuntimeError):
    """A stored value could not be decrypted with any configured key."""


def _decode_key(raw: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(raw.strip() + "=" * (-len(raw.strip()) % 4))
    except (binascii.Error, ValueError):
        raise EncryptionKeyError(
            "The encryption key is not valid base64url. " + KEY_SETUP_HELP
        ) from None
    if len(key) != 32:
        raise EncryptionKeyError("The encryption key must be exactly 32 bytes. " + KEY_SETUP_HELP)
    return key


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def _current_key() -> bytes:
    raw = get_settings().email_settings_encryption_key
    if not raw or not raw.strip():
        raise EncryptionKeyError("EMAIL_SETTINGS_ENCRYPTION_KEY is not set. " + KEY_SETUP_HELP)
    return _decode_key(raw)


def _all_keys() -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    current = _current_key()
    keys[_key_id(current)] = current
    for raw in get_settings().email_settings_previous_keys.split(","):
        if raw.strip():
            old = _decode_key(raw)
            keys.setdefault(_key_id(old), old)
    return keys


def encryption_available() -> bool:
    try:
        _current_key()
    except EncryptionKeyError:
        return False
    return True


def encrypt(plaintext: str, purpose: str) -> str:
    key = _current_key()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), purpose.encode("utf-8"))
    blob = base64.urlsafe_b64encode(nonce + sealed).decode("ascii")
    return f"{_VERSION}:{_key_id(key)}:{blob}"


def decrypt(token: str, purpose: str) -> str:
    try:
        version, key_id, blob = token.split(":", 2)
        raw = base64.urlsafe_b64decode(blob)
    except (ValueError, binascii.Error):
        raise DecryptionError("The stored secret is malformed.") from None
    if version != _VERSION:
        raise DecryptionError("Unsupported secret format.")
    key = _all_keys().get(key_id)
    if key is None:
        raise DecryptionError(
            "The stored secret was encrypted with a key that is not configured. "
            "Restore that key (EMAIL_SETTINGS_PREVIOUS_KEYS) or re-enter the password."
        )
    try:
        plain = AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose.encode("utf-8"))
    except InvalidTag:
        raise DecryptionError("The stored secret failed integrity verification.") from None
    return plain.decode("utf-8")


def key_available_for(token: str) -> bool:
    """True when a configured key matches the token's key id (no decryption done)."""
    try:
        return token.split(":", 2)[1] in _all_keys()
    except (IndexError, EncryptionKeyError):
        return False


def needs_reencryption(token: str) -> bool:
    """True when a value was encrypted with an old key (re-save to rotate)."""
    try:
        return token.split(":", 2)[1] != _key_id(_current_key())
    except (IndexError, EncryptionKeyError):
        return False
