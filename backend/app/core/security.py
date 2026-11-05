"""Password hashing (Argon2id) and opaque token helpers."""

import hashlib
import hmac
import re
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# argon2-cffi defaults follow RFC 9106's recommended Argon2id parameters.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(32))


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown emails can't be detected by timing."""
    verify_password(_dummy_hash(), password)


def validate_password_policy(password: str) -> list[str]:
    """Return a list of policy violations (empty when the password is acceptable)."""
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password) > PASSWORD_MAX_LENGTH:
        problems.append(f"Password must be at most {PASSWORD_MAX_LENGTH} characters.")
    if password.strip() != password:
        problems.append("Password must not start or end with whitespace.")
    if len(set(password)) < 5:
        problems.append("Password is too repetitive.")
    return problems


def new_token() -> str:
    """256-bit URL-safe random token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), expected_hash)


def normalize_email(email: str) -> str:
    return email.strip().lower()


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX_LENGTH = 320


def is_valid_email(email: str) -> bool:
    """Basic structural check; it does not prove the mailbox exists or belongs to anyone."""
    email = normalize_email(email)
    return len(email) <= EMAIL_MAX_LENGTH and bool(_EMAIL_RE.match(email))


def mask_email(email: str) -> str:
    """'someone@example.com' -> 'so***@example.com' for logs."""
    local, _, domain = normalize_email(email).partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"
