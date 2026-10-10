"""Typed request/response models shared by the retrieval service, API and CLI."""

import uuid
from datetime import date, datetime
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


class ContextPassage(BaseModel):
    chunk_id: uuid.UUID
    ordinal: int
    excerpt: str
    section_label: str | None
    page_reference_status: PageStatus
    page_start: int | None = Field(description="0-based PDF page; only when verified")
    page_end: int | None


class PassageContext(BaseModel):
    """A passage with the passages around it in the same judgment, for reading in context."""

    judgment: JudgmentRef
    passage: ContextPassage
    before: list[ContextPassage]
    after: list[ContextPassage]
    attribution: str = ATTRIBUTION
    notice: str = NOTICE


class CourtInfo(BaseModel):
    court_code: str
    court_name: str | None
    judgments: int


class CourtsResponse(BaseModel):
    courts: list[CourtInfo]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The search query limit: the whole question is retrieved against, never a cut-off part.
    question: str = Field(min_length=1, max_length=1000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    # Echoed back only: each question is answered on its own (no conversation memory yet).
    session_id: str | None = Field(default=None, max_length=128)


AbstainReason = Literal[
    "no_results", "model_abstained", "no_supported_claims", "invalid_model_output"
]
ClaimKind = Literal["holding", "obiter", "fact", "inference"]


class ChatPassage(BaseModel):
    chunk_id: uuid.UUID
    excerpt: str
    page_reference_status: PageStatus
    page_start: int | None = Field(description="0-based PDF page; only when verified")
    page_end: int | None


class ChatSource(BaseModel):
    """A judgment cited by the answer; ``number`` is its marker in the answer text."""

    number: int
    judgment: JudgmentRef
    also_published_as: list[JudgmentRef]
    passages: list[ChatPassage]


class ChatClaim(BaseModel):
    text: str
    kind: ClaimKind
    source_numbers: list[int]
    quote: str = Field(description="Verbatim from the passage quote_chunk_id (checked)")
    quote_chunk_id: uuid.UUID
    pinpoint: str | None = Field(
        description="Verified PDF page(s) of the passage holding the quote (1-based), else null"
    )
    support_score: float | None = Field(
        description="Probability that a cited passage entails the claim (NLI model)"
    )


class GenerationInfo(BaseModel):
    provider: str
    model: str = Field(description="The model the provider reports having run")
    requested_model: str = Field(description="The configured model name (may be an alias)")
    prompt_version: str
    support_model: str = Field(description="NLI model@revision that checked the claims")
    input_tokens: int
    output_tokens: int
    latency_ms: int
    sources_sent: int
    source_ids_cited: int
    invalid_source_ids: int
    removed_claims: dict[str, int] = Field(description="Claims dropped by verification, by reason")


class ChatResponse(BaseModel):
    question: str
    session_id: str | None
    abstained: bool
    abstain_reason: AbstainReason | None
    answer: str | None = Field(description="Built from verified claims only; [n] = sources[n]")
    claims: list[ChatClaim]
    sources: list[ChatSource]
    # Server-written notes (removed claims, page references, degraded retrieval).
    limitations: list[str]
    # Written by the model; not verified.
    model_limitations: str | None
    # Cases retrieved for the question, to check by hand (always present when any matched).
    matched_cases: list[JudgmentRef]
    query_info: QueryInfo
    generation: GenerationInfo | None
    attribution: str = ATTRIBUTION
    notice: str = NOTICE


class UserInfo(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: Literal["admin", "researcher", "reviewer"]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    token: str = Field(description="Bearer token; store it HttpOnly and send it on each request")
    expires_at: datetime = Field(description="Absolute expiry (idle sessions end sooner)")
    user: UserInfo


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
