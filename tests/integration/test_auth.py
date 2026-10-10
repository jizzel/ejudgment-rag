import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from ejudgment.api.main import create_app
from ejudgment.auth.service import create_user, set_active
from ejudgment.config import Settings, get_settings
from ejudgment.domain.enums import UserRole
from ejudgment.generation.fake import FakeLLM
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from ejudgment.retention import apply_retention
from ejudgment.verification.entailment import FakeNli
from ejudgment.worker import users as users_cli
from tests.fixtures import legacy_fixture as fx
from tests.integration.test_chat import grounded

pytestmark = pytest.mark.integration

EMAIL = "Ama.Mensah@Example.org"
PASSWORD = "a long enough passphrase"


@pytest.fixture
def secure(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"auth_required": True, "auth_hash_secret": SecretStr("test-secret")}
    )


@pytest.fixture
def user(migrated_engine: Engine, secure: Settings) -> Any:
    with migrated_engine.begin() as conn:
        return create_user(conn, secure, email=EMAIL, display_name="Ama Mensah", password=PASSWORD)


@pytest.fixture
def client(migrated_engine: Engine, secure: Settings) -> Iterator[TestClient]:
    app = create_app(
        secure, migrated_engine, llm=FakeLLM(grounded), nli=FakeNli(), load_models=False
    )
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> Any:
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params))


def test_login_and_session(client: TestClient, user: Any, migrated_engine: Engine) -> None:
    response = _login(client, email="  ama.mensah@EXAMPLE.org ")  # case and spaces don't matter
    assert response.status_code == 200, response.text
    body = response.json()
    token = body["token"]
    assert body["user"] == {
        "id": str(user.id),
        "email": "ama.mensah@example.org",
        "display_name": "Ama Mensah",
        "role": "researcher",
    }
    me = client.get("/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200 and me.json()["email"] == "ama.mensah@example.org"
    # Only the token's SHA-256 is stored; the database never holds a usable token.
    stored = _rows(migrated_engine, "SELECT token_hash FROM sessions")
    assert [row.token_hash for row in stored] == [hashlib.sha256(token.encode()).hexdigest()]


def test_failures_are_generic_and_recorded_without_secrets(
    client: TestClient, user: Any, migrated_engine: Engine
) -> None:
    wrong = _login(client, password="not the password!")
    unknown = _login(client, email="nobody@example.org")
    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "invalid_credentials",
            "message": "Email or password is incorrect",
            "details": None,
        }
    token = _login(client).json()["token"]
    events = _rows(migrated_engine, "SELECT * FROM auth_events ORDER BY created_at")
    assert [e.event for e in events] == ["user_created", "login_failed", "login_failed", "login_ok"]
    assert events[1].user_id == user.id and events[2].user_id is None
    dump = json.dumps([dict(e._mapping) for e in events], default=str).lower()
    for secret in (
        "ama.mensah@example.org",
        "not the password",
        PASSWORD,
        token.lower(),
        "testclient",
    ):
        assert secret not in dump


def test_repeated_failures_lock_the_account_for_a_while(
    client: TestClient, user: Any, migrated_engine: Engine, secure: Settings
) -> None:
    for _ in range(secure.login_max_failures):
        assert _login(client, password="wrong wrong wrong").status_code == 401
    locked = _login(client)  # even the right password, while locked
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "too_many_attempts"
    assert (
        _rows(migrated_engine, "SELECT count(*) AS n FROM auth_events WHERE event = 'locked'")[0].n
        == 1
    )
    with migrated_engine.begin() as conn:  # the window passes
        conn.execute(text("UPDATE auth_events SET created_at = created_at - interval '16 minutes'"))
    assert _login(client).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/courts"),
        ("post", "/v1/search"),
        ("post", "/v1/chat"),
        ("get", "/v1/passages/00000000-0000-0000-0000-000000000000"),
        ("get", "/v1/judgments/00000000-0000-0000-0000-000000000000"),
        ("get", "/v1/auth/me"),
        ("post", "/v1/auth/logout"),
        ("post", "/v1/auth/password"),
    ],
)
def test_every_route_needs_a_session(client: TestClient, method: str, path: str) -> None:
    for headers in ({}, _auth("forged-token"), {"Authorization": "Basic abc"}):
        response = getattr(client, method)(
            path, headers=headers, **({"json": {}} if method == "post" else {})
        )
        assert response.status_code == 401, (path, headers, response.text)
        assert response.json()["error"]["code"] == "unauthenticated"
        assert response.headers["www-authenticate"] == "Bearer"
    assert client.get("/healthz").status_code == 200  # liveness stays open


def test_sessions_end_when_idle_expired_or_logged_out(
    client: TestClient, user: Any, migrated_engine: Engine
) -> None:
    idle, expired, out = (_login(client).json()["token"] for _ in range(3))
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE sessions SET last_seen_at = now() - interval '13 hours' "
                "WHERE token_hash = :h"
            ),
            {"h": hashlib.sha256(idle.encode()).hexdigest()},
        )
        conn.execute(
            text(
                "UPDATE sessions SET expires_at = now() - interval '1 second' WHERE token_hash = :h"
            ),
            {"h": hashlib.sha256(expired.encode()).hexdigest()},
        )
    assert client.get("/v1/auth/me", headers=_auth(idle)).status_code == 401
    assert client.get("/v1/auth/me", headers=_auth(expired)).status_code == 401
    assert client.get("/v1/auth/me", headers=_auth(out)).status_code == 200
    assert client.post("/v1/auth/logout", headers=_auth(out)).status_code == 204
    assert client.get("/v1/auth/me", headers=_auth(out)).status_code == 401


def test_password_change(client: TestClient, user: Any) -> None:
    current, other = _login(client).json()["token"], _login(client).json()["token"]

    def change(old: str, new: str) -> Any:
        return client.post(
            "/v1/auth/password",
            headers=_auth(current),
            json={"current_password": old, "new_password": new},
        )

    assert change("wrong current pass", "another long passphrase").status_code == 403
    weak = change(PASSWORD, "short")
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"
    assert change(PASSWORD, "another long passphrase").status_code == 204
    assert client.get("/v1/auth/me", headers=_auth(other)).status_code == 401  # others ended
    assert client.get("/v1/auth/me", headers=_auth(current)).status_code == 200
    assert _login(client).status_code == 401
    assert _login(client, password="another long passphrase").status_code == 200


def test_disabled_users_lose_their_sessions(
    client: TestClient, user: Any, migrated_engine: Engine, secure: Settings
) -> None:
    token = _login(client).json()["token"]
    with migrated_engine.begin() as conn:
        set_active(conn, secure, EMAIL, False)
    assert client.get("/v1/auth/me", headers=_auth(token)).status_code == 401
    refused = _login(client)
    assert refused.status_code == 401 and refused.json()["error"]["code"] == "invalid_credentials"


def test_queries_are_audited_per_user(
    legacy_fixture: fx.LegacyFixture,
    secure: Settings,
    migrated_engine: Engine,
    client: TestClient,
    user: Any,
) -> None:
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, secure, engine=migrated_engine
    )
    run_chunking(migrated_engine, WhitespaceTokenizer(), secure)
    token = _login(client).json()["token"]
    assert (
        client.post("/v1/search", headers=_auth(token), json={"query": "marker37x3"}).status_code
        == 200
    )
    assert (
        client.post("/v1/chat", headers=_auth(token), json={"question": "marker37x3"}).status_code
        == 200
    )
    audit = _rows(migrated_engine, "SELECT endpoint, user_id FROM query_audit ORDER BY created_at")
    assert [(row.endpoint, row.user_id) for row in audit] == [
        ("/v1/search", user.id),
        ("/v1/chat", user.id),
    ]


def test_admin_cli(
    database_url: str,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        assert (
            users_cli.main(
                ["create", "--email", "Admin@Example.org", "--role", "admin", "--generate"]
            )
            == 0
        )
        created = capsys.readouterr().out
        assert "created admin@example.org (admin)" in created
        password = created.split("password (shown once): ")[1].strip()
        assert users_cli.main(["list"]) == 0
        assert "admin@example.org\tadmin\tactive\tlast login never" in capsys.readouterr().out
        assert users_cli.main(["disable", "admin@example.org"]) == 0
        assert users_cli.main(["reset-password", "admin@example.org", "--generate"]) == 0
        assert password not in capsys.readouterr().out  # a new one
        assert users_cli.main(["disable", "nobody@example.org"]) == 2
    finally:
        get_settings.cache_clear()
    events = _rows(migrated_engine, "SELECT event FROM auth_events ORDER BY created_at")
    assert [e.event for e in events] == [
        "user_created",
        "user_disabled",
        "sessions_revoked",
        "password_changed",
        "sessions_revoked",
    ]


def test_retention_deletes_exactly_what_is_old(
    migrated_engine: Engine, secure: Settings, user: Any
) -> None:
    now = datetime.now(UTC)
    with migrated_engine.begin() as conn:
        for days in (100, 10):
            conn.execute(
                text(
                    "INSERT INTO query_audit (id, created_at, endpoint, query_hash, filters, "
                    "result_judgment_ids, latency_ms) "
                    "VALUES (gen_random_uuid(), :at, '/v1/search', 'h', '{}', '[]', 1)"
                ),
                {"at": now - timedelta(days=days)},
            )
        for days in (400, 10):
            conn.execute(
                text(
                    "INSERT INTO auth_events (id, created_at, event, details) "
                    "VALUES (gen_random_uuid(), :at, 'login_failed', '{}')"
                ),
                {"at": now - timedelta(days=days)},
            )
        for name, expires, revoked in (
            ("old", now - timedelta(days=10), None),
            ("revoked", now + timedelta(days=1), now - timedelta(days=8)),
            ("live", now + timedelta(days=1), None),
        ):
            conn.execute(
                text(
                    "INSERT INTO sessions (token_hash, user_id, last_seen_at, expires_at, "
                    "revoked_at) VALUES (:h, :u, now(), :e, :r)"
                ),
                {"h": name, "u": user.id, "e": expires, "r": revoked},
            )
        for days in (800, 10):
            conn.execute(
                text(
                    "INSERT INTO llm_usage_ledger (id, created_at, endpoint, provider, model, "
                    "input_tokens, output_tokens, cached_input_tokens, estimated_usd, latency_ms, "
                    "status) "
                    "VALUES (gen_random_uuid(), :at, 'x', 'ollama', 'm', 0, 0, 0, 0, 1, 'ok')"
                ),
                {"at": now - timedelta(days=days)},
            )
    assert apply_retention(migrated_engine, secure) == {
        "query_audit": 1,
        "auth_events": 1,
        "sessions": 2,
        "llm_usage_ledger": 1,
    }
    assert set(apply_retention(migrated_engine, secure).values()) == {0}  # idempotent
    assert [r.token_hash for r in _rows(migrated_engine, "SELECT token_hash FROM sessions")] == [
        "live"
    ]


def test_create_user_rules(migrated_engine: Engine, secure: Settings) -> None:
    with migrated_engine.begin() as conn:
        admin = create_user(
            conn,
            secure,
            email="Boss@Example.org",
            display_name="",
            password=PASSWORD,
            role=UserRole.ADMIN,
        )
    assert (admin.email, admin.display_name, admin.role) == (
        "boss@example.org",
        "boss@example.org",
        "admin",
    )
    with pytest.raises(ValueError, match="valid email"), migrated_engine.begin() as conn:
        create_user(conn, secure, email="not-an-email", display_name="x", password=PASSWORD)


def test_unknown_emails_still_verify_a_password(
    client: TestClient, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown email costs the same Argon2 verification, so timing does not reveal it."""
    from ejudgment.auth import service

    calls: list[str] = []
    real = service.verify_password

    def counting(password_hash: str, password: str) -> bool:
        calls.append(password_hash[:9])
        return real(password_hash, password)

    monkeypatch.setattr(service, "verify_password", counting)
    assert _login(client, email="nobody@example.org").status_code == 401
    assert calls == ["$argon2id"]


def _attempt(engine: Engine, settings: Settings, password: str) -> str:
    """One sign-in in its own transaction, committed even on failure (as the API route does)."""
    from ejudgment.auth import service

    with engine.begin() as conn:
        try:
            return service.login(conn, settings, EMAIL, password, client=None).token
        except service.AuthError as exc:
            return exc.code


def test_parallel_failures_cannot_exceed_the_limit(
    migrated_engine: Engine, secure: Settings, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent guesses for one email are checked one at a time against the limit."""
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep

    from ejudgment.auth import service

    real = service.verify_password
    checked: list[int] = []

    def slow(password_hash: str, password: str) -> bool:
        checked.append(1)
        sleep(0.2)  # every request is "in flight" together without serialisation
        return real(password_hash, password)

    monkeypatch.setattr(service, "verify_password", slow)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(
            pool.map(lambda _: _attempt(migrated_engine, secure, "wrong wrong wrong"), range(10))
        )
    assert len(checked) == secure.login_max_failures
    assert sorted(results) == ["invalid_credentials"] * 5 + ["too_many_attempts"] * 5


def test_a_reset_during_sign_in_also_ends_that_session(
    migrated_engine: Engine, secure: Settings, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sign-in that read the old password must not outlive a reset that happens meanwhile."""
    import threading

    from ejudgment.auth import service

    real = service.verify_password
    verified = threading.Event()
    release = threading.Event()

    def paused(password_hash: str, password: str) -> bool:
        result = real(password_hash, password)
        verified.set()
        release.wait(timeout=10)  # the sign-in holds here, mid-transaction
        return result

    monkeypatch.setattr(service, "verify_password", paused)
    outcome: dict[str, str] = {}
    login = threading.Thread(
        target=lambda: outcome.update(token=_attempt(migrated_engine, secure, PASSWORD))
    )
    login.start()
    assert verified.wait(timeout=10)

    def reset() -> None:
        with migrated_engine.begin() as conn:
            service.reset_password(conn, secure, EMAIL, "brand new passphrase!")
        outcome["reset"] = "done"

    resetting = threading.Thread(target=reset)
    resetting.start()
    resetting.join(timeout=1.0)
    assert resetting.is_alive()  # the reset waits for the sign-in to finish
    release.set()
    login.join(timeout=10)
    resetting.join(timeout=10)
    assert outcome["reset"] == "done" and len(outcome["token"]) > 20  # the sign-in did succeed
    with pytest.raises(service.AuthError), migrated_engine.begin() as conn:
        service.resolve_session(conn, secure, outcome["token"])  # ...but the reset ended it


def test_retention_counts_idle_ended_sessions(
    migrated_engine: Engine, secure: Settings, user: Any
) -> None:
    now = datetime.now(UTC)
    with migrated_engine.begin() as conn:
        for name, last_seen in (
            ("idle-8-days", now - timedelta(days=8)),
            ("idle-6-days", now - timedelta(days=6)),
        ):
            conn.execute(
                text(
                    "INSERT INTO sessions (token_hash, user_id, last_seen_at, expires_at) "
                    "VALUES (:h, :u, :seen, :e)"
                ),
                # Abandoned sessions whose absolute expiry is still ahead.
                {"h": name, "u": user.id, "seen": last_seen, "e": now + timedelta(days=1)},
            )
    assert apply_retention(migrated_engine, secure)["sessions"] == 1
    remaining = _rows(migrated_engine, "SELECT token_hash FROM sessions")
    assert [row.token_hash for row in remaining] == ["idle-6-days"]


def test_a_reset_during_a_password_change_wins(
    migrated_engine: Engine, secure: Settings, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user's own password change must not overwrite an admin reset made meanwhile."""
    import threading

    from ejudgment.auth import service

    with migrated_engine.begin() as conn:
        session = service.login(conn, secure, EMAIL, PASSWORD, client=None)
    real = service.verify_password
    verified = threading.Event()
    release = threading.Event()

    def paused(password_hash: str, password: str) -> bool:
        result = real(password_hash, password)
        if not release.is_set():
            verified.set()
            release.wait(timeout=10)  # the change holds here, mid-transaction
        return result

    monkeypatch.setattr(service, "verify_password", paused)

    def change() -> None:
        with migrated_engine.begin() as conn:
            service.change_password(
                conn,
                secure,
                session.user,
                current_password=PASSWORD,
                new_password="self chosen passphrase",
                token=session.token,
            )

    def reset() -> None:
        with migrated_engine.begin() as conn:
            service.reset_password(conn, secure, EMAIL, "admin reset passphrase")

    changing = threading.Thread(target=change)
    changing.start()
    assert verified.wait(timeout=10)
    resetting = threading.Thread(target=reset)
    resetting.start()
    resetting.join(timeout=1.0)
    assert resetting.is_alive()  # the reset waits for the change to finish
    release.set()
    changing.join(timeout=10)
    resetting.join(timeout=10)
    assert _attempt(migrated_engine, secure, "self chosen passphrase") == "invalid_credentials"
    assert len(_attempt(migrated_engine, secure, "admin reset passphrase")) > 20  # a token
