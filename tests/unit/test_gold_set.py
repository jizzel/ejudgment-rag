from pathlib import Path

import pytest
from pydantic import ValidationError

from ejudgment.config import Settings
from ejudgment.evaluation.retrieval import RANKING_SETTINGS, load_gold

REPO_GOLD = Path(__file__).resolve().parents[2] / "evals" / "gold.jsonl"


def test_repository_gold_set_is_valid() -> None:
    questions = load_gold(REPO_GOLD)
    assert len(questions) >= 20
    assert not any(q.reviewed for q in questions)  # engineer-written seed, not lawyer-reviewed
    categories = {q.category for q in questions}
    assert categories == {"citation", "case_name", "issue", "fact_pattern", "out_of_corpus"}
    for question in questions:
        assert all(uri.startswith("/akn/") for uri in question.gold_canonical_uris)


def _write(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(lines))
    return path


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    line = '{"id": "a", "category": "issue", "question": "q", "gold_canonical_uris": ["/akn/x"]}'
    with pytest.raises(ValueError, match="duplicate"):
        load_gold(_write(tmp_path, line, line))


def test_gold_or_no_answer_but_not_both(tmp_path: Path) -> None:
    neither = '{"id": "a", "category": "issue", "question": "q"}'
    with pytest.raises(ValueError, match="expect_no_answer"):
        load_gold(_write(tmp_path, neither))


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    line = '{"id": "a", "category": "issue", "question": "q", "gold": ["/akn/x"]}'
    with pytest.raises(ValidationError):
        load_gold(_write(tmp_path, line))


# Settings that cannot change what retrieval returns or how it ranks results.
NOT_RANKING = {
    "database_url",
    "ingest_batch_size",
    "pdf_verify_pages",
    "pdf_verify_min_window_chars",
    "pdf_verify_min_overlap",
    "source_base_url",
    "search_max_top_k",
    "audit_store_raw_queries",
    "embedding_batch_size",
    # Only how long a vector-coverage count is cached; coverage itself is in the corpus record.
    "embedding_coverage_ttl_seconds",
    # Text extraction: changes corpus text (captured by the corpus digests), not ranking.
    "tesseract_cmd",
    "pdftoppm_cmd",
    "ocr_dpi",
    "ocr_language",
    "ocr_workers",
    "ocr_min_confidence",
    # Generation: changes answers, not retrieval (recorded by answer runs, GENERATION_SETTINGS).
    "llm_provider",
    "ollama_base_url",
    "ollama_chat_model",
    "ollama_num_ctx",
    "llm_timeout_seconds",
    "llm_max_output_tokens",
    "generation_max_passages",
    "generation_passages_per_case",
    "generation_max_context_tokens",
    "generation_case_closing_passages",
    "generation_max_claims",
    "generation_min_quote_words",
    "nli_model_id",
    "nli_revision",
    "nli_max_input_tokens",
    "nli_min_entailment",
    "openai_enabled",
    "openai_api_key",
    "openai_chat_model",
    "openai_reasoning_effort",
    "openai_timeout_seconds",
    "openai_max_retries",
    "openai_max_output_tokens",
    "openai_max_input_tokens",
    "openai_max_calls_per_run",
    "openai_test_budget_usd",
    "openai_prices",
    # Sign-in and retention: who may search, not what search returns.
    "auth_required",
    "session_idle_hours",
    "session_max_days",
    "login_max_failures",
    "login_window_minutes",
    "password_min_length",
    "auth_hash_secret",
    "audit_retention_days",
    "auth_event_retention_days",
    "session_retention_days",
    "usage_retention_days",
}


def test_every_setting_is_either_recorded_or_declared_irrelevant() -> None:
    fields = set(Settings.model_fields)
    recorded = set(RANKING_SETTINGS)
    assert recorded <= fields
    assert fields - recorded == NOT_RANKING, (
        "a new setting must be added to RANKING_SETTINGS (if it can affect retrieval) "
        "or to NOT_RANKING here"
    )
    for name in ("dense_raw_neighbours", "search_max_depth", "embedding_query_instruction"):
        assert name in recorded


def test_smoke_set_is_a_subset_of_the_gold_set() -> None:
    """The pilot's smoke questions are gold questions, copied unchanged."""
    smoke = REPO_GOLD.with_name("smoke.jsonl")
    gold = {q.id: q for q in load_gold(REPO_GOLD)}
    questions = load_gold(smoke)
    assert len(questions) == 5
    assert all(q == gold[q.id] for q in questions)
    assert {q.category for q in questions} == {
        "citation",
        "case_name",
        "issue",
        "fact_pattern",
        "out_of_corpus",
    }
