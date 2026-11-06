"""Authenticated encryption for stored secrets (SMTP password, FBR tokens).

AES-256-GCM with a random 96-bit nonce per encryption and associated data that
binds a ciphertext to its purpose, so it cannot be moved to another column.

Stored format: ``v1:<key_id>:<base64url(nonce || ciphertext+tag)>``, where
``key_id`` is the first 8 hex digits of SHA-256(key). It identifies which key
encrypted a value, so a rotation can tell old values from new ones.

Each kind of secret has its own keyring (key separation), configured only
through the environment / secret manager:
- SMTP password: ``EMAIL_SETTINGS_ENCRYPTION_KEY`` (+ ``EMAIL_SETTINGS_PREVIOUS_KEYS``)
- FBR tokens:    ``FBR_TOKEN_ENCRYPTION_KEY`` (+ ``FBR_TOKEN_PREVIOUS_KEYS``)
The current key encrypts and decrypts; previous keys only decrypt (rotation).
The FBR key must differ from the SMTP key.

There is no fallback and no auto-generated key. If a key is missing or
invalid, operations raise ``EncryptionKeyError`` with setup guidance.
"""

import base64
import binascii
import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_VERSION = "v1"
_NONCE_BYTES = 12


@dataclass(frozen=True)
class Keyring:
    env_name: str
    current_attr: str
    previous_attr: str


EMAIL = Keyring(
    "EMAIL_SETTINGS_ENCRYPTION_KEY", "email_settings_encryption_key", "email_settings_previous_keys"
)
FBR = Keyring("FBR_TOKEN_ENCRYPTION_KEY", "fbr_token_encryption_key", "fbr_token_previous_keys")


def key_setup_help(keyring: Keyring = EMAIL) -> str:
    return (
        f"Set {keyring.env_name} to a base64url-encoded 32-byte key, e.g. the output of: "
        'python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32))'
        '.decode())". Keep it in your secret store and back it up separately from the database.'
    )


KEY_SETUP_HELP = key_setup_help(EMAIL)


class EncryptionKeyError(RuntimeError):
    """The encryption key is missing or invalid."""


class DecryptionError(RuntimeError):
    """A stored value could not be decrypted with any configured key."""


def _decode_key(raw: str, keyring: Keyring) -> bytes:
    try:
        key = base64.urlsafe_b64decode(raw.strip() + "=" * (-len(raw.strip()) % 4))
    except (binascii.Error, ValueError):
        raise EncryptionKeyError(
            "The encryption key is not valid base64url. " + key_setup_help(keyring)
        ) from None
    if len(key) != 32:
        raise EncryptionKeyError(
            "The encryption key must be exactly 32 bytes. " + key_setup_help(keyring)
        )
    return key


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def _current_key(keyring: Keyring = EMAIL) -> bytes:
    settings = get_settings()
    raw = getattr(settings, keyring.current_attr)
    if not raw or not raw.strip():
        raise EncryptionKeyError(f"{keyring.env_name} is not set. " + key_setup_help(keyring))
    key = _decode_key(raw, keyring)
    if keyring is not EMAIL:
        email_raw = settings.email_settings_encryption_key
        if email_raw and email_raw.strip() == raw.strip():
            raise EncryptionKeyError(
                f"{keyring.env_name} must be different from EMAIL_SETTINGS_ENCRYPTION_KEY "
                "(each kind of secret uses its own key)."
            )
    return key


def _all_keys(keyring: Keyring = EMAIL) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    current = _current_key(keyring)
    keys[_key_id(current)] = current
    for raw in (getattr(get_settings(), keyring.previous_attr) or "").split(","):
        if raw.strip():
            old = _decode_key(raw, keyring)
            keys.setdefault(_key_id(old), old)
    return keys


def encryption_available(keyring: Keyring = EMAIL) -> bool:
    try:
        _current_key(keyring)
    except EncryptionKeyError:
        return False
    return True


def encrypt(plaintext: str, purpose: str, keyring: Keyring = EMAIL) -> str:
    key = _current_key(keyring)
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), purpose.encode("utf-8"))
    blob = base64.urlsafe_b64encode(nonce + sealed).decode("ascii")
    return f"{_VERSION}:{_key_id(key)}:{blob}"


def decrypt(token: str, purpose: str, keyring: Keyring = EMAIL) -> str:
    try:
        version, key_id, blob = token.split(":", 2)
        raw = base64.urlsafe_b64decode(blob)
    except (ValueError, binascii.Error):
        raise DecryptionError("The stored secret is malformed.") from None
    if version != _VERSION:
        raise DecryptionError("Unsupported secret format.")
    key = _all_keys(keyring).get(key_id)
    if key is None:
        raise DecryptionError(
            "The stored secret was encrypted with a key that is not configured. "
            f"Restore that key ({keyring.env_name.replace('ENCRYPTION_KEY', 'PREVIOUS_KEYS')}) "
            "or enter the secret again."
        )
    try:
        plain = AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose.encode("utf-8"))
    except InvalidTag:
        raise DecryptionError("The stored secret failed integrity verification.") from None
    return plain.decode("utf-8")


def key_available_for(token: str, keyring: Keyring = EMAIL) -> bool:
    """True when a configured key matches the token's key id (no decryption done)."""
    try:
        return token.split(":", 2)[1] in _all_keys(keyring)
    except (IndexError, EncryptionKeyError):
        return False


def needs_reencryption(token: str, keyring: Keyring = EMAIL) -> bool:
    """True when a value was encrypted with an old key (re-save to rotate)."""
    try:
        return token.split(":", 2)[1] != _key_id(_current_key(keyring))
    except (IndexError, EncryptionKeyError):
        return False
