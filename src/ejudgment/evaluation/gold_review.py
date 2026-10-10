"""Gold-set review: lawyers curate evaluation questions in the app; evals/gold.jsonl is exported.

A question is a ``draft`` until a reviewer approves it (then it counts as ``reviewed`` in
evaluations); ``retired`` questions stay for history but are not exported. Every change is
versioned (optimistic concurrency: a stale ``version`` is refused) and recorded in
``gold_question_history``. Reviewer identity stays in the database; the exported file has none.
"""

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, func, insert, select, text, update
from sqlalchemy.engine import Connection

from ejudgment.domain.enums import GoldAction, GoldStatus
from ejudgment.domain.models import GoldQuestionHistory, GoldQuestionRecord
from ejudgment.domain.schemas import SearchFilters
from ejudgment.evaluation.retrieval import (
    Category,
    GoldPassage,
    GoldQuestion,
    gold_problems,
    load_gold,
)

QUESTIONS = cast(Table, GoldQuestionRecord.__table__)
HISTORY = cast(Table, GoldQuestionHistory.__table__)
REVIEW_TARGET = (50, 100)  # AGENTS.md: grow to 50-100 lawyer-reviewed questions


class GoldReviewError(Exception):
    """Mapped to the API's error shape: ``{"error": {"code", "message"}}``."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class GoldExportError(Exception):
    """The export would not load: nothing was written. ``problems`` maps question id to why."""

    def __init__(self, problems: dict[str, list[str]]) -> None:
        self.problems = problems
        details = "; ".join(f"{qid}: {', '.join(p)}" for qid, p in problems.items())
        super().__init__(
            f"{len(problems)} question(s) are not complete enough to export (finish or retire "
            f"them first): {details}"
        )


# One question-id allocation at a time (same key in every process), until the transaction ends.
_ID_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"ejudgment-gold-ids").digest()[:8], "big", signed=True
)


class GoldDraft(BaseModel):
    """What a reviewer edits."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    category: Category
    filters: SearchFilters = Field(default_factory=SearchFilters)
    expect_no_answer: bool = False
    gold_canonical_uris: list[str] = Field(default_factory=list, max_length=50)
    gold_passages: list[GoldPassage] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=5000)


@dataclass(frozen=True)
class ImportReport:
    created: int
    unchanged: int
    differs: list[str]  # ids already in the database with other content (not overwritten)


def _now() -> datetime:
    return datetime.now(UTC)


def to_gold(row: Any) -> GoldQuestion:
    approved = row.status == GoldStatus.APPROVED.value
    return GoldQuestion(
        id=row.id,
        question=row.question,
        category=row.category,
        filters=SearchFilters.model_validate(row.filters or {}),
        gold_canonical_uris=list(row.gold_canonical_uris or []),
        gold_passages=[GoldPassage.model_validate(p) for p in row.gold_passages or []],
        expect_no_answer=row.expect_no_answer,
        reviewed=approved,
        reviewed_at=row.reviewed_at if approved else None,
        notes=row.notes,
    )


def _values(draft: GoldDraft) -> dict[str, Any]:
    return {
        "question": draft.question.strip(),
        "category": draft.category,
        "filters": draft.filters.applied(),
        "expect_no_answer": draft.expect_no_answer,
        "gold_canonical_uris": list(dict.fromkeys(draft.gold_canonical_uris)),
        "gold_passages": [p.model_dump() for p in draft.gold_passages],
        "notes": draft.notes,
    }


def _history(
    conn: Connection, question_id: str, user_id: uuid.UUID | None, action: GoldAction
) -> None:
    row = conn.execute(select(QUESTIONS).where(QUESTIONS.c.id == question_id)).one()
    snapshot = {
        "status": row.status,
        "version": row.version,
        **to_gold(row).model_dump(mode="json", exclude={"reviewed", "reviewed_at"}),
    }
    conn.execute(
        insert(HISTORY).values(
            id=uuid.uuid4(),
            question_id=question_id,
            user_id=user_id,
            action=action.value,
            snapshot=snapshot,
        )
    )


def get_question(conn: Connection, question_id: str, *, lock: bool = False) -> Any:
    query = select(QUESTIONS).where(QUESTIONS.c.id == question_id)
    row = conn.execute(query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise GoldReviewError(404, "gold_question_not_found", f"No gold question {question_id}")
    return row


def _locked(conn: Connection, question_id: str, version: int) -> Any:
    row = get_question(conn, question_id, lock=True)
    if row.version != version:
        raise GoldReviewError(
            409,
            "version_conflict",
            "This question was changed by someone else; reload it and apply your changes again",
        )
    return row


def history(conn: Connection, question_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(HISTORY)
            .where(HISTORY.c.question_id == question_id)
            .order_by(HISTORY.c.created_at)
        )
    )


def list_questions(
    conn: Connection, *, status: str | None = None, category: str | None = None
) -> list[Any]:
    query = select(QUESTIONS).order_by(QUESTIONS.c.id)
    if status:
        query = query.where(QUESTIONS.c.status == status)
    if category:
        query = query.where(QUESTIONS.c.category == category)
    return list(conn.execute(query))


def counts(conn: Connection) -> dict[str, Any]:
    by_status: dict[str, int] = dict(
        conn.execute(select(QUESTIONS.c.status, func.count()).group_by(QUESTIONS.c.status)).all()
    )
    by_category: dict[str, int] = dict(
        conn.execute(
            select(QUESTIONS.c.category, func.count())
            .where(QUESTIONS.c.status == GoldStatus.APPROVED.value)
            .group_by(QUESTIONS.c.category)
        ).all()
    )
    return {
        "by_status": {s.value: int(by_status.get(s.value, 0)) for s in GoldStatus},
        "approved_by_category": {k: int(v) for k, v in sorted(by_category.items())},
        "target": {"min": REVIEW_TARGET[0], "max": REVIEW_TARGET[1]},
    }


def _next_id(conn: Connection) -> str:
    """The next free ``q-NNNN``. Holds a transaction-scoped lock, so concurrent creations
    queue here instead of choosing the same id."""
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ID_LOCK_KEY})
    ids = conn.execute(select(QUESTIONS.c.id).where(QUESTIONS.c.id.like("q-%"))).scalars()
    numbers = [int(m.group(1)) for i in ids if (m := re.fullmatch(r"q-(\d+)", i))]
    return f"q-{max(numbers, default=0) + 1:04d}"


def create_question(conn: Connection, draft: GoldDraft, user_id: uuid.UUID | None) -> str:
    question_id = _next_id(conn)
    conn.execute(
        insert(QUESTIONS).values(
            id=question_id,
            status=GoldStatus.DRAFT.value,
            version=1,
            created_by=user_id,
            updated_by=user_id,
            **_values(draft),
        )
    )
    _history(conn, question_id, user_id, GoldAction.CREATED)
    return question_id


def update_question(
    conn: Connection, question_id: str, draft: GoldDraft, version: int, user_id: uuid.UUID | None
) -> None:
    """Saves the labels. Editing an approved question returns it to draft (re-approval)."""
    row = _locked(conn, question_id, version)
    if row.status == GoldStatus.RETIRED.value:
        raise GoldReviewError(409, "gold_question_retired", "Reopen the question to edit it")
    conn.execute(
        update(QUESTIONS)
        .where(QUESTIONS.c.id == question_id)
        .values(
            **_values(draft),
            status=GoldStatus.DRAFT.value,
            reviewed_by=None,
            reviewed_at=None,
            version=row.version + 1,
            updated_by=user_id,
            updated_at=_now(),
        )
    )
    _history(conn, question_id, user_id, GoldAction.EDITED)


def approve_question(
    conn: Connection, question_id: str, version: int, user_id: uuid.UUID | None
) -> None:
    """A reviewer confirms the labels: valid gold cases (or an expected abstention) needed."""
    row = _locked(conn, question_id, version)
    if row.status != GoldStatus.DRAFT.value:
        raise GoldReviewError(
            409, "invalid_transition", f"A {row.status} question can't be approved"
        )
    gold = to_gold(row).model_copy(update={"reviewed": True, "reviewed_at": _now()})
    problems = gold_problems(gold)
    if problems:
        raise GoldReviewError(422, "gold_invalid", "; ".join(problems))
    conn.execute(
        update(QUESTIONS)
        .where(QUESTIONS.c.id == question_id)
        .values(
            status=GoldStatus.APPROVED.value,
            reviewed_by=user_id,
            reviewed_at=gold.reviewed_at,
            version=row.version + 1,
            updated_by=user_id,
            updated_at=_now(),
        )
    )
    _history(conn, question_id, user_id, GoldAction.APPROVED)


def _set_status(
    conn: Connection,
    question_id: str,
    version: int,
    user_id: uuid.UUID | None,
    status: GoldStatus,
    action: GoldAction,
    allowed_from: tuple[GoldStatus, ...],
) -> None:
    row = _locked(conn, question_id, version)
    if row.status not in {s.value for s in allowed_from}:
        raise GoldReviewError(
            409, "invalid_transition", f"A {row.status} question can't be {action.value}"
        )
    conn.execute(
        update(QUESTIONS)
        .where(QUESTIONS.c.id == question_id)
        .values(
            status=status.value,
            reviewed_by=None,
            reviewed_at=None,
            version=row.version + 1,
            updated_by=user_id,
            updated_at=_now(),
        )
    )
    _history(conn, question_id, user_id, action)


def reopen_question(
    conn: Connection, question_id: str, version: int, user_id: uuid.UUID | None
) -> None:
    _set_status(
        conn,
        question_id,
        version,
        user_id,
        GoldStatus.DRAFT,
        GoldAction.REOPENED,
        (GoldStatus.APPROVED, GoldStatus.RETIRED),
    )


def retire_question(
    conn: Connection, question_id: str, version: int, user_id: uuid.UUID | None
) -> None:
    _set_status(
        conn,
        question_id,
        version,
        user_id,
        GoldStatus.RETIRED,
        GoldAction.RETIRED,
        (GoldStatus.DRAFT, GoldStatus.APPROVED),
    )


def import_questions(
    conn: Connection, questions: list[GoldQuestion], user_id: uuid.UUID | None = None
) -> ImportReport:
    """Adds questions not yet in the database (idempotent by id; existing ones are never
    overwritten, and differences are reported)."""
    created = unchanged = 0
    differs: list[str] = []
    for question in questions:
        existing = conn.execute(
            select(QUESTIONS).where(QUESTIONS.c.id == question.id)
        ).one_or_none()
        if existing is not None:
            current = to_gold(existing).model_dump(exclude={"reviewed_at"})
            if current == question.model_dump(exclude={"reviewed_at"}):
                unchanged += 1
            else:
                differs.append(question.id)
            continue
        conn.execute(
            insert(QUESTIONS).values(
                id=question.id,
                question=question.question,
                category=question.category,
                filters=question.filters.applied(),
                expect_no_answer=question.expect_no_answer,
                gold_canonical_uris=question.gold_canonical_uris,
                gold_passages=[p.model_dump() for p in question.gold_passages],
                notes=question.notes,
                status=(GoldStatus.APPROVED if question.reviewed else GoldStatus.DRAFT).value,
                reviewed_at=question.reviewed_at,
                version=1,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        _history(conn, question.id, user_id, GoldAction.IMPORTED)
        created += 1
    return ImportReport(created, unchanged, differs)


def export_questions(conn: Connection) -> list[GoldQuestion]:
    """Every question that is not retired, in id order; approved ones are ``reviewed``."""
    rows = conn.execute(
        select(QUESTIONS)
        .where(QUESTIONS.c.status != GoldStatus.RETIRED.value)
        .order_by(QUESTIONS.c.id)
    )
    return [to_gold(row) for row in rows]


def render_jsonl(questions: list[GoldQuestion]) -> str:
    return "".join(
        q.model_dump_json(exclude_none=True, exclude_defaults=True, by_alias=True) + "\n"
        for q in questions
    )


def export_jsonl(conn: Connection, path: Path) -> int:
    """Writes the export only if every question is valid and the written file loads; the
    existing file is replaced atomically and otherwise left untouched."""
    questions = export_questions(conn)
    problems = {q.id: found for q in questions if (found := gold_problems(q))}
    if problems:
        raise GoldExportError(problems)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(render_jsonl(questions), encoding="utf-8")
    try:
        load_gold(temporary)  # exactly what the evaluation workers will read
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(questions)
