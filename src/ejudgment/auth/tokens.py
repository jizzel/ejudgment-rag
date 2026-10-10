"""Session tokens and privacy-preserving hashes for the security audit."""

import hashlib
import hmac
import secrets
from functools import lru_cache

from ejudgment.config import Settings

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    """What the sessions table stores: a database leak does not reveal usable tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _process_salt() -> bytes:
    return secrets.token_bytes(32)


def audit_hash(settings: Settings, value: str) -> str:
    """Keyed hash of an email or client address for auth_events (never stored in clear)."""
    secret = settings.auth_hash_secret
    key = secret.get_secret_value().encode("utf-8") if secret else _process_salt()
    return hmac.new(key, value.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()
