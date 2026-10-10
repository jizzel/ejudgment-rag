"""Accounts, sign-in and sessions. All functions take a connection inside a transaction.

Security properties (tested):
- one generic error for an unknown email, a wrong password and a disabled account, with an
  Argon2 verification in every case so timing does not reveal which;
- at most ``login_max_failures`` failures per email within ``login_window_minutes``;
- bearer tokens are stored only as SHA-256 hashes; sessions end after ``session_idle_hours``
  without use and ``session_max_days`` in any case, on logout, password change or disabling;
- ``auth_events`` records sign-ins, failures, lockouts and account changes with hashed email
  and client, never passwords or tokens.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Table, func, insert, select, text, update
from sqlalchemy.engine import Connection

from ejudgment.auth.passwords import (
    check_new_password,
    dummy_hash,
    hash_password,
    needs_rehash,
    verify_password,
)
from ejudgment.auth.tokens import audit_hash, new_token, token_hash
from ejudgment.config import Settings
from ejudgment.domain.enums import AuthEventKind, UserRole
from ejudgment.domain.models import AuthEvent, User, UserSession

USERS = cast(Table, User.__table__)
SESSIONS = cast(Table, UserSession.__table__)
EVENTS = cast(Table, AuthEvent.__table__)


class AuthError(Exception):
    """Mapped to the API's error shape: ``{"error": {"code", "message"}}``."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


INVALID_CREDENTIALS = AuthError(401, "invalid_credentials", "Email or password is incorrect")
UNAUTHENTICATED = AuthError(401, "unauthenticated", "Sign in to continue")


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str
    display_name: str
    role: str


@dataclass(frozen=True)
class NewSession:
    token: str
    expires_at: datetime
    user: AuthUser


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _now() -> datetime:
    return datetime.now(UTC)


def record_event(
    conn: Connection,
    settings: Settings,
    kind: AuthEventKind,
    *,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
    client: str | None = None,
    **details: Any,
) -> None:
    conn.execute(
        insert(EVENTS).values(
            id=uuid.uuid4(),
            user_id=user_id,
            email_hash=audit_hash(settings, email) if email else None,
            event=kind.value,
            client_hash=audit_hash(settings, client) if client else None,
            details=details,
        )
    )


def _user(row: Any) -> AuthUser:
    return AuthUser(row.id, row.email, row.display_name, row.role)


def create_user(
    conn: Connection,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    password: str,
    role: UserRole = UserRole.RESEARCHER,
) -> AuthUser:
    email = normalise_email(email)
    if "@" not in email or len(email) > 320:
        raise ValueError("A valid email address is required")
    check_new_password(password, min_length=settings.password_min_length, email=email)
    user_id = uuid.uuid4()
    conn.execute(
        insert(USERS).values(
            id=user_id,
            email=email,
            display_name=display_name.strip() or email,
            password_hash=hash_password(password),
            role=role.value,
            is_active=True,
        )
    )
    record_event(conn, settings, AuthEventKind.USER_CREATED, user_id=user_id, role=role.value)
    return AuthUser(user_id, email, display_name.strip() or email, role.value)


def recent_failures(conn: Connection, settings: Settings, email: str) -> int:
    since = _now() - timedelta(minutes=settings.login_window_minutes)
    return int(
        conn.execute(
            select(func.count())
            .select_from(EVENTS)
            .where(
                EVENTS.c.email_hash == audit_hash(settings, email),
                EVENTS.c.event == AuthEventKind.LOGIN_FAILED.value,
                EVENTS.c.created_at >= since,
            )
        ).scalar_one()
    )


def _login_lock_key(email: str) -> int:
    """A stable 64-bit advisory-lock key per email (the same in every API process)."""
    digest = hashlib.sha256(b"ejudgment-login:" + email.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def login(
    conn: Connection, settings: Settings, email: str, password: str, *, client: str | None
) -> NewSession:
    email = normalise_email(email)
    # One sign-in per email at a time (also unknown emails), until this transaction commits
    # its outcome: parallel requests cannot all read a failure count below the limit.
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _login_lock_key(email)})
    if recent_failures(conn, settings, email) >= settings.login_max_failures:
        record_event(conn, settings, AuthEventKind.LOCKED, email=email, client=client)
        raise AuthError(
            429,
            "too_many_attempts",
            f"Too many failed sign-ins; try again in {settings.login_window_minutes:.0f} minutes",
        )
    # Locked until commit: a password reset, change or disabling (which update this row) waits
    # for this sign-in and then ends its session too, or commits first so the old password fails.
    row = conn.execute(select(USERS).where(USERS.c.email == email).with_for_update()).one_or_none()
    # Verify even when there is no such account, so the answer time does not reveal it.
    valid = verify_password(row.password_hash if row else dummy_hash(), password)
    if row is None or not valid or not row.is_active:
        record_event(
            conn,
            settings,
            AuthEventKind.LOGIN_FAILED,
            user_id=row.id if row else None,
            email=email,
            client=client,
            reason="inactive" if row is not None and valid else "credentials",
        )
        raise INVALID_CREDENTIALS
    values: dict[str, Any] = {"last_login_at": _now()}
    if needs_rehash(row.password_hash):
        values["password_hash"] = hash_password(password)
    conn.execute(update(USERS).where(USERS.c.id == row.id).values(**values))
    session = _start_session(conn, settings, row.id)
    record_event(conn, settings, AuthEventKind.LOGIN_OK, user_id=row.id, email=email, client=client)
    return NewSession(session[0], session[1], _user(row))


def _start_session(
    conn: Connection, settings: Settings, user_id: uuid.UUID
) -> tuple[str, datetime]:
    token = new_token()
    now = _now()
    expires_at = now + timedelta(days=settings.session_max_days)
    conn.execute(
        insert(SESSIONS).values(
            token_hash=token_hash(token),
            user_id=user_id,
            last_seen_at=now,
            expires_at=expires_at,
        )
    )
    return token, expires_at


def resolve_session(conn: Connection, settings: Settings, token: str) -> AuthUser:
    """The signed-in user of a bearer token, sliding its idle timeout; else 401."""
    now = _now()
    row = conn.execute(
        select(USERS, SESSIONS.c.token_hash)
        .join(SESSIONS, SESSIONS.c.user_id == USERS.c.id)
        .where(
            SESSIONS.c.token_hash == token_hash(token),
            SESSIONS.c.revoked_at.is_(None),
            SESSIONS.c.expires_at > now,
            SESSIONS.c.last_seen_at > now - timedelta(hours=settings.session_idle_hours),
            USERS.c.is_active.is_(True),
        )
    ).one_or_none()
    if row is None:
        raise UNAUTHENTICATED
    conn.execute(
        update(SESSIONS).where(SESSIONS.c.token_hash == row.token_hash).values(last_seen_at=now)
    )
    return _user(row)


def logout(conn: Connection, settings: Settings, token: str, user: AuthUser) -> None:
    conn.execute(
        update(SESSIONS)
        .where(SESSIONS.c.token_hash == token_hash(token), SESSIONS.c.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    record_event(conn, settings, AuthEventKind.LOGOUT, user_id=user.id)


def revoke_sessions(
    conn: Connection,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    keep_token: str | None = None,
    reason: str,
) -> int:
    query = update(SESSIONS).where(SESSIONS.c.user_id == user_id, SESSIONS.c.revoked_at.is_(None))
    if keep_token is not None:
        query = query.where(SESSIONS.c.token_hash != token_hash(keep_token))
    revoked = conn.execute(query.values(revoked_at=_now())).rowcount
    record_event(
        conn,
        settings,
        AuthEventKind.SESSIONS_REVOKED,
        user_id=user_id,
        reason=reason,
        count=revoked,
    )
    return revoked


def change_password(
    conn: Connection,
    settings: Settings,
    user: AuthUser,
    *,
    current_password: str,
    new_password: str,
    token: str,
) -> None:
    """Needs the current password; ends the user's other sessions."""
    row = conn.execute(select(USERS).where(USERS.c.id == user.id)).one()
    if not verify_password(row.password_hash, current_password):
        raise AuthError(403, "invalid_credentials", "The current password is incorrect")
    check_new_password(new_password, min_length=settings.password_min_length, email=row.email)
    _set_password(conn, user.id, new_password)
    record_event(conn, settings, AuthEventKind.PASSWORD_CHANGED, user_id=user.id, by="self")
    revoke_sessions(conn, settings, user.id, keep_token=token, reason="password_changed")


def _set_password(conn: Connection, user_id: uuid.UUID, password: str) -> None:
    conn.execute(
        update(USERS)
        .where(USERS.c.id == user_id)
        .values(password_hash=hash_password(password), password_changed_at=_now())
    )


def find_user(conn: Connection, email: str) -> Any:
    row = conn.execute(select(USERS).where(USERS.c.email == normalise_email(email))).one_or_none()
    if row is None:
        raise LookupError(f"No user {normalise_email(email)!r}")
    return row


def reset_password(conn: Connection, settings: Settings, email: str, password: str) -> None:
    """Admin reset: sets a new password and ends all the user's sessions."""
    row = find_user(conn, email)
    check_new_password(password, min_length=settings.password_min_length, email=row.email)
    _set_password(conn, row.id, password)
    record_event(conn, settings, AuthEventKind.PASSWORD_CHANGED, user_id=row.id, by="admin")
    revoke_sessions(conn, settings, row.id, reason="password_reset")


def set_active(conn: Connection, settings: Settings, email: str, active: bool) -> None:
    row = find_user(conn, email)
    conn.execute(update(USERS).where(USERS.c.id == row.id).values(is_active=active))
    kind = AuthEventKind.USER_ENABLED if active else AuthEventKind.USER_DISABLED
    record_event(conn, settings, kind, user_id=row.id)
    if not active:
        revoke_sessions(conn, settings, row.id, reason="user_disabled")


def list_users(conn: Connection) -> list[Any]:
    return list(
        conn.execute(
            select(
                USERS.c.email,
                USERS.c.display_name,
                USERS.c.role,
                USERS.c.is_active,
                USERS.c.created_at,
                USERS.c.last_login_at,
            ).order_by(USERS.c.email)
        )
    )
