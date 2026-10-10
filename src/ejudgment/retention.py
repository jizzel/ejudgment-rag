"""Data retention (AGENTS.md "Retention policy"): delete what is no longer needed.

- query_audit rows (hashed queries) after ``audit_retention_days``;
- auth_events after ``auth_event_retention_days``;
- sessions ended (absolute expiry, idle timeout or revocation, whichever came first) more than
  ``session_retention_days`` ago;
- llm_usage_ledger rows (cost record, no text) after ``usage_retention_days``.
evaluation_runs are kept: they are the reproducibility record. Idempotent.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import Engine, Table, delete, or_

from ejudgment.config import Settings
from ejudgment.domain.models import AuthEvent, LlmUsage, QueryAudit, UserSession

QUERY_AUDIT = cast(Table, QueryAudit.__table__)
AUTH_EVENTS = cast(Table, AuthEvent.__table__)
SESSIONS = cast(Table, UserSession.__table__)
LEDGER = cast(Table, LlmUsage.__table__)


def apply_retention(
    engine: Engine, settings: Settings, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)

    def before(days: int) -> datetime:
        return now - timedelta(days=days)

    ended = before(settings.session_retention_days)
    with engine.begin() as conn:
        return {
            "query_audit": conn.execute(
                delete(QUERY_AUDIT).where(
                    QUERY_AUDIT.c.created_at < before(settings.audit_retention_days)
                )
            ).rowcount,
            "auth_events": conn.execute(
                delete(AUTH_EVENTS).where(
                    AUTH_EVENTS.c.created_at < before(settings.auth_event_retention_days)
                )
            ).rowcount,
            "sessions": conn.execute(
                delete(SESSIONS).where(
                    or_(
                        SESSIONS.c.expires_at < ended,
                        SESSIONS.c.revoked_at < ended,
                        # Ended by the idle timeout: last use + idle hours.
                        SESSIONS.c.last_seen_at
                        < ended - timedelta(hours=settings.session_idle_hours),
                    )
                )
            ).rowcount,
            "llm_usage_ledger": conn.execute(
                delete(LEDGER).where(LEDGER.c.created_at < before(settings.usage_retention_days))
            ).rowcount,
        }
