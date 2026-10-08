"""Typed request/response models shared by the retrieval service, API and CLI."""

import uuid
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ATTRIBUTION = (
    "Source: Ghana Legal Information Institute (GhaLII, ghalii.org), "
    "licensed CC BY-NC 4.0. Non-commercial use with attribution."
)
NOTICE = (
    "Assisted legal research, not legal advice. Corpus coverage may be incomplete; "
    "absence of a result does not mean absence in Ghanaian law."
)

_CODE = r"^[a-z0-9-]{2,64}$"


class SearchFilters(BaseModel):
    """Strict filters: applied exactly, never widened."""

    model_config = ConfigDict(extra="forbid")

    court: str | None = Field(default=None, pattern=_CODE, description="AKN court code")
    jurisdiction: str | None = Field(default=None, pattern=_CODE, description="AKN code")
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    judge: str | None = Field(default=None, min_length=2, max_length=100)

    @model_validator(mode="after")
    def _years_ordered(self) -> Self:
        if self.year_from is not None and self.year_to is not None:
            if self.year_from > self.year_to:
                raise ValueError("year_from must not be after year_to")
        return self

    def applied(self) -> dict[str, str | int]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


SearchMode = Literal["hybrid", "lexical", "dense"]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=50)
    # offset + top_k is further limited by the search_max_depth setting (stable pages).
    offset: int = Field(default=0, ge=0, le=500)
    mode: SearchMode = "hybrid"
    rerank: bool = True


# citation/case_name: exact lookups; lexical/dense: found by one channel; hybrid: by both.
MatchType = Literal["citation", "case_name", "lexical", "dense", "hybrid"]
PageStatus = Literal["verified", "unknown", "pending"]


class JudgmentRef(BaseModel):
    judgment_id: uuid.UUID
    canonical_uri: str
    citation: str
    title: str | None
    court_code: str | None
    court_name: str | None
    jurisdiction: str | None
    judgment_date: date | None
    source_url: str


class PassageResult(BaseModel):
    chunk_id: uuid.UUID
    judgment: JudgmentRef
    excerpt: str
    section_label: str | None
    paragraph_refs: list[str]
    page_reference_status: PageStatus
    page_start: int | None = Field(description="Set only when page_reference_status=verified")
    page_end: int | None
    match_type: MatchType
    lexical_score: float | None = None
    dense_score: float | None = Field(default=None, description="Cosine similarity")
    rrf_score: float | None = None
    rerank_score: float | None = None


class CaseResult(BaseModel):
    """One case; ``judgments`` lists every URI publishing the same text."""

    judgment: JudgmentRef
    also_published_as: list[JudgmentRef]
    match_type: MatchType
    score: float
    passages: list[PassageResult]


class QueryInfo(BaseModel):
    detected_citation: str | None
    looks_like_case_name: bool
    filters_applied: dict[str, str | int]
    mode_requested: SearchMode = "hybrid"
    mode_used: SearchMode = "hybrid"
    reranked: bool = False
    # Set when a model was unavailable and retrieval fell back (never silently).
    degraded: bool = False
    degraded_reason: str | None = None


class SearchResponse(BaseModel):
    query: str
    passages: list[PassageResult]
    cases: list[CaseResult]
    query_info: QueryInfo
    attribution: str = ATTRIBUTION
    notice: str = NOTICE


class SourceInfo(BaseModel):
    kind: str
    mime_type: str | None
    verification_status: str
    rights_status: str
    original_url: str | None


class JudgmentDetail(BaseModel):
    judgment: JudgmentRef
    case_number: str | None
    language: str | None
    judges: list[str]
    neutral_citation: str | None
    source_status: str
    sources: list[SourceInfo]
    chunk_count: int
    attribution: str = ATTRIBUTION
    notice: str = NOTICE


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
