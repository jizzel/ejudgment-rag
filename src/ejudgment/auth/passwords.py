"""Password hashing with Argon2id (argon2-cffi's recommended parameters)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()


class WeakPassword(ValueError):
    """A new password does not meet the minimum rules."""


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)


# Computed once at import, before any request: hashing it lazily would make the first
# unknown-email sign-in do an extra Argon2 hash, a timing difference that reveals the email.
_DUMMY_HASH = _HASHER.hash("not-a-real-password-for-timing-only")


def dummy_hash() -> str:
    """Verified against for unknown emails, so they take as long as wrong passwords."""
    return _DUMMY_HASH


def check_new_password(password: str, *, min_length: int, email: str) -> None:
    if len(password) < min_length:
        raise WeakPassword(f"Passwords need at least {min_length} characters")
    if password.strip().lower() == email.strip().lower():
        raise WeakPassword("The password must not be the email address")
    if len(set(password)) < 4:
        raise WeakPassword("The password is too repetitive")
