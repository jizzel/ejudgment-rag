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
