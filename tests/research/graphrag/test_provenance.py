"""Run provenance: build ids, dirty trees, baseline matching, per-case temporal checks."""

import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from ejudgment.config import Settings
from experiments.graphrag.baseline import current_config, mismatches
from experiments.graphrag.coverage.profile_mentions import ChunkRow, SourceInfo, reference_record
from experiments.graphrag.extraction.mentions import find_references
from experiments.graphrag.manifest import build_id, git_state
from experiments.graphrag.resolution.index import CorpusIndex, Judgment, neutral_key


def test_a_limited_profile_does_not_share_the_full_build_id() -> None:
    versions, corpus = {"resolver": "resolver-v2"}, {"judgments_digest": "j", "chunks_digest": "c"}
    assert build_id(versions, corpus, {"limit": None}) != build_id(
        versions, corpus, {"limit": 3000}
    )
    assert build_id(versions, corpus, {"limit": None}) == build_id(
        versions, corpus, {"limit": None}
    )


def test_untracked_source_files_make_the_tree_dirty(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / ".gitignore").write_text("artifacts/\n")
    git("add", ".gitignore")
    git("-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "mentions.jsonl").write_text("{}\n")
    assert git_state(tmp_path)["git_dirty"] is False  # ignored artifacts don't count
    (tmp_path / "new_resolver.py").write_text("VERSION = 'x'\n")
    assert git_state(tmp_path)["git_dirty"] is True  # an untracked source file does


CURRENT: dict[str, Any] = {
    "gold_sha256": "g",
    "settings": {"rrf_k": 60, "rerank_top_n": 30},
    "embedding_model": {"model_id": "bge", "revision": "r1"},
    "reranker_model": {"model_id": "minilm", "revision": "r2"},
    "embedding_template_version": "ctx-v1",
    "corpus": {"chunks_digest": "c", "embeddings_digest": "e", "vector_indexes": {"ix": "def"}},
}


def test_baseline_run_must_match_settings_models_and_vectors() -> None:
    stored = {
        **CURRENT,
        "embedding_model": {**CURRENT["embedding_model"], "dimension": 384},  # extra detail
    }
    assert mismatches(stored, CURRENT) == []
    changed = {
        **stored,
        "settings": {"rrf_k": 60, "rerank_top_n": 20},
        "reranker_model": {"model_id": "minilm", "revision": "r3"},
        "corpus": {**CURRENT["corpus"], "embeddings_digest": "other"},
    }
    assert mismatches(changed, CURRENT) == [
        "settings.rerank_top_n",
        "reranker_model.revision",
        "corpus.embeddings_digest",
    ]


def test_current_config_covers_settings_models_and_the_full_corpus(settings: Settings) -> None:
    corpus = {"chunks_digest": "c", "embeddings_digest": "e", "vector_indexes": {"ix": "def"}}
    current = current_config(settings, "g", corpus)
    assert current["corpus"] == corpus
    assert current["embedding_model"] == {
        "model_id": settings.embedding_model_id,
        "revision": settings.embedding_revision,
    }
    assert current["reranker_model"]["revision"] == settings.reranker_revision
    assert current["settings"]["rerank_top_n"] == settings.rerank_top_n
    assert set(current) == {
        "gold_sha256",
        "settings",
        "embedding_model",
        "reranker_model",
        "embedding_template_version",
        "corpus",
    }


def _judgment(jid: str, title: str, neutral: str, day: date, group: str) -> Judgment:
    return Judgment(
        jid, f"/akn/{jid}", group, title, f"{title} {neutral}", neutral_key(neutral), day, "ghasc"
    )


def test_temporal_check_uses_the_citing_case_not_the_copy() -> None:
    # The citing case was published twice: 2020 and a later-dated 2024 copy. Its target is
    # dated 2022, so the edge is a temporal conflict whichever copy holds the citation.
    index = CorpusIndex.build(
        [
            _judgment("copy-a", "Ofori Vrs Ade", "[2020] GHASC 1", date(2020, 1, 1), "g-citing"),
            _judgment("copy-b", "Ofori Vrs Ade", "[2024] GHASC 9", date(2024, 1, 1), "g-citing"),
            _judgment("target", "Kotei Vrs Kotei", "[2022] GHASC 5", date(2022, 1, 1), "g-target"),
        ]
    )
    text = "x " * 900 + "It was held in [2022] GHASC 5 that"
    (reference,) = find_references(text)
    statuses = set()
    for copy in ("copy-a", "copy-b"):
        chunk = ChunkRow(f"c-{copy}", 3, copy, "g-citing", 0, text, "s", "unknown")
        record = reference_record(index, chunk, SourceInfo("legacy", None), reference)
        statuses.add(record["status"])
    assert statuses == {"temporal_conflict"}
