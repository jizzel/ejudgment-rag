import math
import uuid
from datetime import date

import pytest

from ejudgment.config import Settings
from ejudgment.domain.schemas import SearchRequest
from ejudgment.embeddings.base import ModelUnavailable
from ejudgment.embeddings.fake import FakeEmbeddingProvider, FakeReranker
from ejudgment.embeddings.template import TEMPLATE_VERSION, build_input, context_prefix
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from ejudgment.retrieval.hybrid import apply_rerank, rrf_fuse
from ejudgment.retrieval.repository import JudgmentRow, PassageRow, vector_literal
from ejudgment.retrieval.service import SearchDepthExceeded, search

TOK = WhitespaceTokenizer()


def _input(content: str, title: str | None = "Mensah v Owusu", max_tokens: int = 512) -> str:
    return build_input(
        content,
        title=title,
        court_name="Supreme Court",
        judgment_date=date(2020, 3, 18),
        section="JUDGMENT",
        tokenizer=TOK,
        max_tokens=max_tokens,
    ).text


def test_context_prefix() -> None:
    assert context_prefix("Mensah v Owusu", "Supreme Court", date(2020, 1, 1), "RULING") == (
        "Mensah v Owusu | Supreme Court | 2020\nRULING"
    )
    assert context_prefix(None, None, None, None) == ""


def test_input_keeps_content_verbatim_after_context() -> None:
    text = _input("The appeal is   allowed.\nCosts to the appellant.")
    assert text == (
        "Mensah v Owusu | Supreme Court | 2020\nJUDGMENT\n\n"
        "The appeal is   allowed.\nCosts to the appellant."
    )


def test_long_context_is_trimmed_never_the_content() -> None:
    content = " ".join(f"w{i}" for i in range(20))
    long_title = " ".join(f"party{i}" for i in range(50))
    text = _input(content, title=long_title, max_tokens=30)
    assert text.endswith(content)
    assert TOK.count([text])[0] + 2 <= 30


def test_content_over_the_model_limit_is_an_error() -> None:
    with pytest.raises(ValueError, match="tokens"):
        _input(" ".join(["x"] * 600))


def test_input_hash_tracks_metadata_and_template() -> None:
    def hashed(title: str) -> str:
        return build_input(
            "same content",
            title=title,
            court_name=None,
            judgment_date=None,
            section=None,
            tokenizer=TOK,
            max_tokens=512,
        ).input_hash

    assert hashed("A v B") == hashed("A v B")
    assert hashed("A v B") != hashed("A v C")  # metadata change => re-embed
    assert TEMPLATE_VERSION == "ctx-v1"


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    provider = FakeEmbeddingProvider(synonyms={"landlord": "tenancy"})
    a, b = provider.embed_documents(["tenancy dispute", "tenancy dispute"])
    assert a == b
    assert math.isclose(sum(x * x for x in a), 1.0)
    query = provider.embed_query("landlord dispute")
    assert query == a  # the synonym maps onto the same vocabulary
    assert len(query) == provider.dimension == 384


def test_fake_reranker_prefers_overlap() -> None:
    scores = FakeReranker().score("tenancy arrears", ["tenancy arrears due", "goats stolen"])
    assert scores[0] > scores[1]


def _row(name: str) -> PassageRow:
    judgment = JudgmentRow(uuid.uuid4(), f"/akn/{name}", name, name, None, None, None, None)
    return PassageRow(
        judgment=judgment,
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, name),
        content=name,
        content_hash=name,
        source_text_hash=name,
        section_label=None,
        paragraph_refs=[],
        page_reference_status="unknown",
        page_start=None,
        page_end=None,
        score=1.0,
    )


def test_rrf_fusion() -> None:
    a, b, c = _row("a"), _row("b"), _row("c")
    fused = rrf_fuse([a, b], [(b, 0.9), (c, 0.8)], k=60)
    assert [x.row.content for x in fused] == ["b", "a", "c"]
    assert math.isclose(fused[0].rrf_score or 0, 1 / 62 + 1 / 61)  # lexical #2, dense #1
    assert (fused[0].lexical_rank, fused[0].dense_rank) == (2, 1)
    assert math.isclose(fused[1].rrf_score or 0, 1 / 61)


def test_rrf_ties_keep_lexical_order_first() -> None:
    a, b = _row("a"), _row("b")
    fused = rrf_fuse([a], [(b, 0.5)], k=60)  # both 1/61
    assert [x.row.content for x in fused] == ["a", "b"]


def test_rerank_reorders_only_the_head() -> None:
    rows = [_row(n) for n in "abcd"]
    candidates = rrf_fuse(rows, [], k=60)
    reranked = apply_rerank(candidates, [0.1, 0.9, 0.5])
    assert [c.row.content for c in reranked] == ["b", "c", "a", "d"]
    assert reranked[-1].rerank_score is None


def test_vector_literal() -> None:
    assert vector_literal([0.5, -0.25, 1e-9]) == "[0.5,-0.25,1e-09]"


def test_depth_is_limited_before_touching_the_database() -> None:
    request = SearchRequest(query="x", top_k=10, offset=145)
    with pytest.raises(SearchDepthExceeded, match="150"):
        search(None, request, Settings())  # type: ignore[arg-type]


def test_real_models_when_cached() -> None:
    from ejudgment.embeddings.sentence_transformers import SentenceTransformerProvider
    from ejudgment.retrieval.rerank import CrossEncoderReranker

    settings = Settings(model_device="cpu")
    try:
        embedder = SentenceTransformerProvider(settings)
        reranker = CrossEncoderReranker(settings)
    except ModelUnavailable:
        pytest.skip("models not in the local HF cache (run fetch-models)")
    tenant, goats = embedder.embed_documents(
        ["The landlord sought possession for unpaid rent.", "The accused stole three goats."]
    )
    query = embedder.embed_query("eviction for rent arrears")
    assert len(query) == 384
    similarity = [sum(q * d for q, d in zip(query, doc, strict=True)) for doc in (tenant, goats)]
    assert similarity[0] > similarity[1]
    assert (reranker.model_id, reranker.model_revision) == (
        settings.reranker_model_id,
        settings.reranker_revision,
    )
    scores = reranker.score(
        "eviction for rent arrears",
        ["The landlord sought possession for unpaid rent.", "The accused stole three goats."],
    )
    assert scores[0] > scores[1]


def _copy(name: str, uri: str) -> PassageRow:
    """One URI's copy of a passage shared by a republished judgment."""
    judgment = JudgmentRow(uuid.uuid4(), uri, name, name, None, None, None, None)
    return PassageRow(
        judgment=judgment,
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, uri),
        content="shared passage",
        content_hash="same-content",
        source_text_hash="same-source",
        section_label=None,
        paragraph_refs=[],
        page_reference_status="unknown",
        page_start=None,
        page_end=None,
        score=1.0,
    )


def test_republished_copies_fuse_into_one_candidate() -> None:
    first_uri = _copy("A v B", "/akn/gh/judgment/ghasc/2020/104/eng@2020-03-18")
    other_uri = _copy("A v B (republished)", "/akn/gh/judgment/ghasc/2020/105/eng@2020-03-18")
    unrelated = _row("z")
    # Lexical kept the first URI's copy; dense kept the other copy (different embedding).
    fused = rrf_fuse([first_uri, unrelated], [(other_uri, 0.9)], k=60)
    shared = [c for c in fused if c.row.content_hash == "same-content"]
    assert len(shared) == 1
    (candidate,) = shared
    assert (candidate.lexical_rank, candidate.dense_rank) == (1, 1)
    assert math.isclose(candidate.rrf_score or 0, 2 / 61)
    assert candidate.row.judgment.canonical_uri == first_uri.judgment.canonical_uri
    assert fused[0] is candidate


def test_same_text_in_different_judgments_is_not_merged() -> None:
    a = _copy("A v B", "/akn/a")
    b = _copy("C v D", "/akn/b")
    b = PassageRow(**{**b.__dict__, "source_text_hash": "another-source"})
    fused = rrf_fuse([a], [(b, 0.9)], k=60)
    assert len(fused) == 2  # a quoted statute in two different judgments stays two passages
