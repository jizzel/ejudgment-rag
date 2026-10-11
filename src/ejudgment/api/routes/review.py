"""Gold-set review for lawyers (role ``reviewer`` or ``admin``)."""

from datetime import datetime
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ejudgment.api.dependencies import (
    CurrentUserDep,
    EngineDep,
    LLMDep,
    NLIDep,
    ProvidersDep,
    SettingsDep,
    require_user,
)
from ejudgment.api.errors import ApiError
from ejudgment.auth.service import AuthError, AuthUser
from ejudgment.domain.enums import GoldAction, GoldStatus, UserRole
from ejudgment.domain.models import User
from ejudgment.domain.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    JudgmentRef,
    SearchRequest,
    SearchResponse,
)
from ejudgment.evaluation import gold_review as review
from ejudgment.evaluation.retrieval import Category, GoldPassage
from ejudgment.generation.base import LLMUnavailable
from ejudgment.generation.budget import BudgetExhausted
from ejudgment.generation.chat import answer_question
from ejudgment.retrieval.service import judgment_refs, search

REVIEW_ROLES = {UserRole.REVIEWER.value, UserRole.ADMIN.value}
CANDIDATE_CASES = 15


def require_reviewer(user: CurrentUserDep) -> AuthUser | None:
    """Reviewers and admins only (``None`` only when sign-in is switched off, in tests)."""
    if user is not None and user.role not in REVIEW_ROLES:
        raise AuthError(403, "forbidden", "Reviewing the gold set needs the reviewer role")
    return user


ReviewerDep = Annotated[AuthUser | None, Depends(require_reviewer)]
router = APIRouter(prefix="/v1/review", dependencies=[Depends(require_user)])
_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422)
}


class ReviewQuestion(BaseModel):
    id: str
    status: GoldStatus
    version: int
    question: str
    category: Category
    filters: dict[str, Any]
    expect_no_answer: bool
    gold_canonical_uris: list[str]
    gold_passages: list[GoldPassage]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None = Field(description="Reviewer's display name")


class ReviewSummary(BaseModel):
    id: str
    status: GoldStatus
    category: Category
    question: str
    gold_cases: int
    gold_passages: int
    updated_at: datetime


class ReviewTarget(BaseModel):
    min: int
    max: int


class ReviewCounts(BaseModel):
    by_status: dict[str, int]
    approved_by_category: dict[str, int]
    target: ReviewTarget


class ReviewList(BaseModel):
    questions: list[ReviewSummary]
    counts: ReviewCounts


class HistoryEntry(BaseModel):
    action: GoldAction
    user: str | None
    created_at: datetime


class ReviewDetail(BaseModel):
    question: ReviewQuestion
    history: list[HistoryEntry]
    candidates: SearchResponse = Field(description="What search returns now (with the filters)")
    gold_cases: list[JudgmentRef] = Field(
        description="The gold cases that are eligible judgments (a URI missing here is not)"
    )


class ReviewWrite(review.GoldDraft):
    version: int = Field(ge=1)


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class Created(BaseModel):
    id: str


def _names(engine: Any, ids: set[Any]) -> dict[Any, str]:
    ids.discard(None)
    if not ids:
        return {}
    users = User.__table__
    with engine.connect() as conn:
        rows = conn.execute(select(users.c.id, users.c.display_name).where(users.c.id.in_(ids)))
        return {row.id: row.display_name for row in rows}


def _question(row: Any, names: dict[Any, str]) -> ReviewQuestion:
    return ReviewQuestion(
        id=row.id,
        status=row.status,
        version=row.version,
        question=row.question,
        category=row.category,
        filters=row.filters or {},
        expect_no_answer=row.expect_no_answer,
        gold_canonical_uris=list(row.gold_canonical_uris or []),
        gold_passages=[GoldPassage.model_validate(p) for p in row.gold_passages or []],
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
        reviewed_at=row.reviewed_at,
        reviewed_by=names.get(row.reviewed_by),
    )


@router.get("/questions", response_model=ReviewList, responses=_ERRORS)
def list_questions(
    engine: EngineDep,
    _: ReviewerDep,
    status: str | None = Query(default=None, pattern="^(draft|approved|retired)$"),
    category: str | None = Query(default=None, max_length=32),
) -> ReviewList:
    with engine.connect() as conn:
        rows = review.list_questions(conn, status=status, category=category)
        counts = review.counts(conn)
    return ReviewList(
        questions=[
            ReviewSummary(
                id=row.id,
                status=row.status,
                category=row.category,
                question=row.question,
                gold_cases=len(row.gold_canonical_uris or []),
                gold_passages=len(row.gold_passages or []),
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        counts=ReviewCounts.model_validate(counts),
    )


@router.get("/questions/{question_id}", response_model=ReviewDetail, responses=_ERRORS)
def read_question(
    question_id: str,
    engine: EngineDep,
    settings: SettingsDep,
    providers: ProvidersDep,
    _: ReviewerDep,
) -> ReviewDetail:
    embedder, reranker = providers
    with engine.connect() as conn:
        row = review.get_question(conn, question_id)
        entries = review.history(conn, question_id)
        gold = review.to_gold(row)
        gold_cases = judgment_refs(conn, gold.gold_canonical_uris, settings)
        candidates = search(
            conn,
            SearchRequest(query=gold.question[:1000], filters=gold.filters, top_k=CANDIDATE_CASES),
            settings,
            embedder=embedder,
            reranker=reranker,
        )
    names = _names(engine, {row.reviewed_by, *(entry.user_id for entry in entries)})
    return ReviewDetail(
        question=_question(row, names),
        history=[
            HistoryEntry(action=e.action, user=names.get(e.user_id), created_at=e.created_at)
            for e in entries
        ],
        candidates=candidates,
        gold_cases=gold_cases,
    )


@router.post("/questions", response_model=Created, status_code=201, responses=_ERRORS)
def create_question(body: review.GoldDraft, engine: EngineDep, user: ReviewerDep) -> Created:
    with engine.begin() as conn:
        return Created(id=review.create_question(conn, body, user.id if user else None))


@router.put("/questions/{question_id}", status_code=204, responses=_ERRORS)
def update_question(
    question_id: str, body: ReviewWrite, engine: EngineDep, user: ReviewerDep
) -> None:
    draft = review.GoldDraft.model_validate(body.model_dump(exclude={"version"}))
    with engine.begin() as conn:
        review.update_question(conn, question_id, draft, body.version, user.id if user else None)


def _transition(
    change: Any, question_id: str, body: VersionBody, engine: Any, user: AuthUser | None
) -> None:
    with engine.begin() as conn:
        change(conn, question_id, body.version, user.id if user else None)


@router.post("/questions/{question_id}/approve", status_code=204, responses=_ERRORS)
def approve(question_id: str, body: VersionBody, engine: EngineDep, user: ReviewerDep) -> None:
    """Mark the labels as lawyer-reviewed (gold cases, or an expected abstention, required)."""
    _transition(review.approve_question, question_id, body, engine, user)


@router.post("/questions/{question_id}/reopen", status_code=204, responses=_ERRORS)
def reopen(question_id: str, body: VersionBody, engine: EngineDep, user: ReviewerDep) -> None:
    _transition(review.reopen_question, question_id, body, engine, user)


@router.post("/questions/{question_id}/retire", status_code=204, responses=_ERRORS)
def retire(question_id: str, body: VersionBody, engine: EngineDep, user: ReviewerDep) -> None:
    _transition(review.retire_question, question_id, body, engine, user)


@router.post(
    "/questions/{question_id}/preview-answer",
    response_model=ChatResponse,
    responses={**_ERRORS, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def preview_answer(
    question_id: str,
    engine: EngineDep,
    settings: SettingsDep,
    providers: ProvidersDep,
    llm: LLMDep,
    nli: NLIDep,
    user: ReviewerDep,
) -> ChatResponse:
    """What the system answers today (the normal pipeline; audited for the reviewer)."""
    if llm is None:
        raise ApiError(503, "llm_unavailable", "No language model is configured")
    if nli is None:
        raise ApiError(
            503, "verifier_unavailable", "The answer verification model is not available"
        )

    def load() -> Any:
        with engine.connect() as conn:
            return review.to_gold(review.get_question(conn, question_id))

    gold = await anyio.to_thread.run_sync(load)
    embedder, reranker = providers
    try:
        return await answer_question(
            engine,
            ChatRequest(question=gold.question, filters=gold.filters),
            settings,
            embedder=embedder,
            reranker=reranker,
            llm=llm,
            nli=nli,
            endpoint="/v1/review/preview-answer",
            user_id=user.id if user else None,
        )
    except LLMUnavailable as exc:
        raise ApiError(503, "llm_unavailable", str(exc)) from exc
    except BudgetExhausted as exc:
        raise ApiError(429, "budget_exhausted", str(exc)) from exc


@router.get("/judgments", response_model=SearchResponse, responses=_ERRORS)
def find_judgment(
    engine: EngineDep,
    settings: SettingsDep,
    _: ReviewerDep,
    citation: str = Query(min_length=3, max_length=300),
) -> SearchResponse:
    """Find a case by citation or name, to add a gold case search did not return."""
    with engine.connect() as conn:
        response = search(
            conn,
            SearchRequest(query=citation, top_k=5, mode="lexical", rerank=False),
            settings,
        )
    exact = [c for c in response.cases if c.match_type in ("citation", "case_name")]
    return response.model_copy(update={"cases": exact or response.cases})
