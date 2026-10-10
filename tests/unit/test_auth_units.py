import hashlib

import pytest
from pydantic import SecretStr

from ejudgment.auth.passwords import (
    WeakPassword,
    check_new_password,
    hash_password,
    needs_rehash,
    verify_password,
)
from ejudgment.auth.tokens import audit_hash, new_token, token_hash
from ejudgment.config import Settings


def test_passwords_are_argon2id_and_verified() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$") and "correct" not in hashed
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "correct horse batterY")
    assert not verify_password("not-a-hash", "anything")  # corrupt hash: a failure, not a crash
    assert not needs_rehash(hashed)


@pytest.mark.parametrize(
    ("password", "message"),
    [("short", "at least 12"), ("a@b.org", "at least 12"), ("aaaaaaaaaaaaaa", "repetitive")],
)
def test_weak_passwords_are_refused(password: str, message: str) -> None:
    with pytest.raises(WeakPassword, match=message):
        check_new_password(password, min_length=12, email="a@b.org")
    with pytest.raises(WeakPassword, match="email"):
        check_new_password("Someone@Example.org", min_length=12, email="someone@example.org")


def test_tokens_are_random_and_stored_only_as_hashes() -> None:
    first, second = new_token(), new_token()
    assert first != second and len(first) >= 40
    assert token_hash(first) == hashlib.sha256(first.encode()).hexdigest() != first


def test_audit_hashes_are_keyed_and_normalised() -> None:
    keyed = Settings(auth_hash_secret=SecretStr("one"))
    other = Settings(auth_hash_secret=SecretStr("two"))
    assert audit_hash(keyed, " A@B.org ") == audit_hash(keyed, "a@b.org")
    assert audit_hash(keyed, "a@b.org") != audit_hash(other, "a@b.org")
    assert audit_hash(keyed, "a@b.org") != hashlib.sha256(b"a@b.org").hexdigest()


def test_sign_in_is_required_by_default() -> None:
    assert Settings().auth_required is True


def test_the_dummy_hash_is_ready_before_any_request() -> None:
    """Unknown-email sign-ins must not do an extra Argon2 hash (a timing tell), not even the
    first one after start-up: the dummy hash exists once the module is loaded. Checked in a
    fresh process, as at start-up."""
    import subprocess
    import sys

    script = (
        "from argon2 import PasswordHasher\n"
        "from ejudgment.auth import passwords\n"
        "calls = []\n"
        "real = PasswordHasher.hash\n"
        "PasswordHasher.hash = lambda self, *a, **k: (calls.append(1), real(self, *a, **k))[1]\n"
        "assert passwords.dummy_hash().startswith('$argon2id$')\n"
        "assert not passwords.verify_password(passwords.dummy_hash(), 'anything')\n"
        "print(len(calls))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=60
    )
    assert result.stdout.strip() == "0"  # no hashing at request time
