import pytest

from ejudgment.ingestion.chunking import (
    PageReferenceStatus,
    SourcePage,
    SourceText,
    chunk_source,
    chunker_version,
    is_heading,
)
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer

TOK = WhitespaceTokenizer()


def _legacy(text: str) -> SourceText:
    return SourceText([SourcePage(text, None)], PageReferenceStatus.UNKNOWN)


def _words(n: int, stem: str = "word") -> str:
    return " ".join(f"{stem}{i}" for i in range(n))


def _chunk(source: SourceText, target: int = 50, maximum: int = 60) -> list:  # type: ignore[type-arg]
    return chunk_source(source, TOK, target_tokens=target, max_tokens=maximum)


def test_chunks_are_exact_spans_within_budget() -> None:
    paragraphs = [f"{_words(20, f'p{i}w')}." for i in range(12)]
    source = _legacy("\n\n".join(paragraphs))
    chunks = _chunk(source)
    assert len(chunks) > 1
    for chunk in chunks:
        assert source.text[chunk.char_start : chunk.char_end] == chunk.content
        assert chunk.token_count <= 60
        assert chunk.token_count == TOK.count([chunk.content])[0]
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    # Paragraphs are packed whole: no chunk starts or ends mid-paragraph.
    assert all(c.content.endswith(".") for c in chunks)


def test_blank_lines_containing_spaces_separate_paragraphs() -> None:
    source = _legacy(f"{_words(40, 'a')}.\n   \n  {_words(40, 'b')}.")
    chunks = _chunk(source)
    assert [c.content.split()[0] for c in chunks] == ["a0", "b0"]


def test_heading_starts_new_chunk_and_labels_following_chunks() -> None:
    text = f"{_words(35, 'intro')}.\n\nJUDGMENT\n{_words(35, 'body')}.\n\n{_words(55, 'more')}."
    chunks = _chunk(_legacy(text))
    assert chunks[0].section_label is None
    assert chunks[1].content.startswith("JUDGMENT")
    assert chunks[1].section_label == "JUDGMENT"
    assert chunks[2].section_label == "JUDGMENT"


@pytest.mark.parametrize(
    "line",
    ["JUDGMENT", "RULING:", "CORAM:", "1. BACKGROUND", "B. ISSUES FOR DETERMINATION", "CONCLUSION"],
)
def test_is_heading(line: str) -> None:
    assert is_heading(line)


@pytest.mark.parametrize(
    "line",
    ["IN THE SUPREME COURT OF GHANA", "Judgment", "The judgment of the court", "JUDGMENT " * 10],
)
def test_is_not_heading(line: str) -> None:
    assert not is_heading(line)


def test_oversized_paragraph_splits_at_sentences_not_citations_or_abbreviations() -> None:
    sentences = [
        f"In Mensah v. Owusu [2019] GHASC 12 the court held {_words(15, 'x')}.",
        f"Section 4 of Act No. 29 was cited by Kwame J.S.C. here {_words(15, 'y')}.",
        f"The appeal therefore fails {_words(15, 'z')}.",
    ]
    text = " ".join(sentences)
    chunks = _chunk(_legacy(text), target=30, maximum=30)
    assert [c.content for c in chunks] == sentences


def test_unsplittable_text_falls_back_to_token_windows() -> None:
    text = _words(130)  # no sentence ends at all
    chunks = _chunk(_legacy(text), target=50, maximum=50)
    assert [c.token_count for c in chunks] == [50, 50, 30]
    assert " ".join(c.content for c in chunks) == text


def test_paragraph_refs() -> None:
    text = (
        f"[12] {_words(8)}.\n\n"
        f"13. {_words(35)}.\n\n"
        "1. Vincent Agu\n\n"  # a short numbered party line is not a judgment paragraph
        f"[14] {_words(8)}."
    )
    chunks = _chunk(_legacy(text), target=200, maximum=200)
    assert chunks[0].paragraph_refs == ["12", "13", "14"]


def test_legacy_text_never_gets_page_bounds() -> None:
    chunks = _chunk(_legacy("\n\n".join(_words(30, f"p{i}") for i in range(5))))
    assert all(c.page_reference_status is PageReferenceStatus.UNKNOWN for c in chunks)
    assert all(c.page_start is None and c.page_end is None for c in chunks)


def test_verified_pages_map_to_page_bounds() -> None:
    pages = [SourcePage(f"{_words(40, f'page{i}w')}.", i) for i in range(3)]
    source = SourceText(pages, PageReferenceStatus.VERIFIED)
    chunks = _chunk(source, target=45, maximum=60)
    assert [(c.page_start, c.page_end) for c in chunks] == [(0, 0), (1, 1), (2, 2)]
    spanning = _chunk(source, target=120, maximum=130)
    assert (spanning[0].page_start, spanning[0].page_end) == (0, 2)


def test_pending_pages_have_no_bounds() -> None:
    source = SourceText([SourcePage(_words(20), 0)], PageReferenceStatus.PENDING)
    (chunk,) = _chunk(source)
    assert (chunk.page_start, chunk.page_end) == (None, None)
    assert chunk.page_reference_status is PageReferenceStatus.PENDING


def test_verified_requires_page_indexes() -> None:
    with pytest.raises(ValueError, match="page_index"):
        _chunk(SourceText([SourcePage("x", None)], PageReferenceStatus.VERIFIED))


def test_deterministic_and_versioned() -> None:
    source = _legacy("\n\n".join(_words(30, f"p{i}") for i in range(8)))
    assert _chunk(source) == _chunk(source)
    assert chunker_version(TOK, 350, 400) != chunker_version(TOK, 300, 400)
    assert "whitespace" in chunker_version(TOK, 350, 400)


def test_empty_text_yields_no_chunks() -> None:
    assert _chunk(_legacy("   \n\n  ")) == []


def test_tiny_chunks_merge_into_a_neighbour() -> None:
    text = f"1\n\nRULING\n\nCORAM:\n{_words(40, 'body')}.\n\n{_words(45, 'tail')}.\n\n2"
    chunks = _chunk(_legacy(text))
    assert all(c.token_count >= 30 for c in chunks)
    assert chunks[0].content.startswith("1\n\nRULING")
    assert chunks[0].section_label == "CORAM"
    assert chunks[-1].content.endswith("2")
