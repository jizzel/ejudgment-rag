"""Split a judgment's text into token-budgeted chunks along legal structure.

Pure and deterministic: no database access. Every chunk is an exact span of the source text
(``text[char_start:char_end] == content``), so quotes stay verbatim. Boundaries prefer, in
order: recognised legal headings, paragraphs (blank lines), sentence ends (never inside a
neutral citation or after a legal abbreviation), and finally token windows.
"""

import bisect
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ejudgment.domain.enums import PageReferenceStatus
from ejudgment.ingestion.hashing import sha256_text
from ejudgment.ingestion.tokenizer import Tokenizer

ALGORITHM_VERSION = "para-v2"
PAGE_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class SourcePage:
    text: str
    page_index: int | None  # 0-based physical PDF page; None = no page mapping


@dataclass(frozen=True)
class SourceText:
    pages: Sequence[SourcePage]
    page_reference_status: PageReferenceStatus

    @property
    def text(self) -> str:
        """The text chunk offsets refer to: pages joined by a blank line."""
        return PAGE_SEPARATOR.join(page.text for page in self.pages)


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    content: str
    char_start: int
    char_end: int
    token_count: int
    section_label: str | None
    paragraph_refs: list[str]
    page_start: int | None
    page_end: int | None
    page_reference_status: PageReferenceStatus
    content_hash: str


def chunker_version(tokenizer: Tokenizer, target_tokens: int, max_tokens: int) -> str:
    return f"{ALGORITHM_VERSION}-t{target_tokens}-m{max_tokens}-{tokenizer.name}"


# --- segmentation -------------------------------------------------------------------------

_BLANK_LINE = re.compile(r"\n[ \t\r\f\v]*\n")
_HEADING_WORDS = (
    "JUDGMENT|JUDGEMENT|RULING|CORAM|FACTS|BACKGROUND|INTRODUCTION|ISSUES?|ANALYSIS|"
    "EVALUATION|HOLDINGS?|DECISION|CONCLUSIONS?|ORDERS?|DISPOSITION|EVIDENCE|SUBMISSIONS|"
    "THE LAW|GROUNDS? OF APPEAL|RESOLUTION|DETERMINATION|REASONS?|COSTS"
)
_HEADING = re.compile(
    rf"^\s*(?:(?:[IVXLC]+|\d{{1,2}}|[A-Z])[.)]\s+)?(?:[A-Z][A-Z ,&'-]*\s)?(?:{_HEADING_WORDS})"
    r"(?:\s+[A-Z][A-Z ,&'-]*)?\s*:?\s*$"
)
_HEADING_MAX_CHARS = 60
_BRACKET_PARAGRAPH = re.compile(r"^\s*\[(\d{1,3})\]")
_NUMBERED_PARAGRAPH = re.compile(r"^\s*(\d{1,3})\.\s+\S")
# A numbered line only counts as a judgment paragraph if it is substantial (not a party list).
_NUMBERED_PARAGRAPH_MIN_TOKENS = 30

_NEUTRAL_CITATION = re.compile(
    r"\[\d{4}\]\s*[A-Za-z][A-Za-z0-9]*\s*\d+|\(\d{4}\)\s*\d+\s*[A-Z][A-Za-z.]*\s*\d*"
)
_SENTENCE_END = re.compile(r"[.?!;:](?=[\"')\]]?\s+[\"'(\[]?[A-Z0-9])")
_ABBREVIATIONS = frozenset(
    {
        "no", "nos", "v", "vs", "vrs", "j", "jj", "jsc", "ja", "cj", "j.s.c", "j.a", "ltd",
        "co", "inc", "mr", "mrs", "ms", "dr", "prof", "hon", "s", "ss", "sec", "art", "arts",
        "para", "paras", "p", "pp", "cf", "e.g", "i.e", "etc", "al", "op", "cit", "ibid",
        "supra", "rev", "st", "esq", "gov", "govt", "corp", "dept", "ord", "cap", "vol",
    }
)  # fmt: skip


@dataclass
class _Unit:
    start: int
    end: int
    is_heading: bool = False
    tokens: int = 0


@dataclass
class _Chunk:
    start: int
    end: int
    tokens: int
    section_label: str | None
    paragraph_refs: list[str] = field(default_factory=list)


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def is_heading(line: str) -> bool:
    stripped = line.strip()
    return (
        0 < len(stripped) <= _HEADING_MAX_CHARS
        and stripped.upper() == stripped
        and bool(_HEADING.match(stripped))
    )


def _blocks(text: str) -> list[_Unit]:
    """Paragraph blocks (separated by blank lines), with heading lines split out."""
    units: list[_Unit] = []
    position = 0
    for match in [*_BLANK_LINE.finditer(text), None]:
        block_end = match.start() if match else len(text)
        segment_start = position
        offset = position
        # Split heading lines out of the block so they start a new chunk.
        for line in text[position:block_end].splitlines(keepends=True):
            line_start, line_end = offset, offset + len(line)
            if is_heading(line):
                start, end = _trim(text, segment_start, line_start)
                if start < end:
                    units.append(_Unit(start, end))
                start, end = _trim(text, line_start, line_end)
                units.append(_Unit(start, end, is_heading=True))
                segment_start = line_end
            offset = line_end
        start, end = _trim(text, segment_start, block_end)
        if start < end:
            units.append(_Unit(start, end))
        position = match.end() if match else len(text)
    return units


def _protected_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _NEUTRAL_CITATION.finditer(text)]


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    segment = text[start:end]
    protected = _protected_spans(segment)
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(segment):
        boundary = match.end()
        if any(lo < boundary < hi for lo, hi in protected):
            continue
        if segment[match.start()] == ".":
            word = re.search(r"([A-Za-z.]+)$", segment[cursor : match.start()])
            if word:
                token = word.group(1).lower().strip(".")
                if token in _ABBREVIATIONS or len(token) == 1:
                    continue
        s, e = _trim(text, start + cursor, start + boundary)
        if s < e:
            spans.append((s, e))
        cursor = boundary
    s, e = _trim(text, start + cursor, end)
    if s < e:
        spans.append((s, e))
    return spans


def _token_windows(
    text: str, start: int, end: int, tokenizer: Tokenizer, max_tokens: int
) -> list[tuple[int, int]]:
    offsets = tokenizer.offsets(text[start:end])
    if not offsets:
        return [(start, end)]
    windows: list[tuple[int, int]] = []
    for index in range(0, len(offsets), max_tokens):
        window = offsets[index : index + max_tokens]
        s, e = _trim(text, start + window[0][0], start + window[-1][1])
        if s < e:
            windows.append((s, e))
    return windows


def _fit_units(text: str, units: list[_Unit], tokenizer: Tokenizer, max_tokens: int) -> list[_Unit]:
    """Split oversized units by sentences, then by token windows."""
    counts = tokenizer.count([text[u.start : u.end] for u in units])
    fitted: list[_Unit] = []
    for unit, count in zip(units, counts, strict=True):
        if count <= max_tokens:
            fitted.append(_Unit(unit.start, unit.end, unit.is_heading, count))
            continue
        sentences = _sentence_spans(text, unit.start, unit.end)
        sentence_counts = tokenizer.count([text[s:e] for s, e in sentences])
        for (s, e), sentence_count in zip(sentences, sentence_counts, strict=True):
            if sentence_count <= max_tokens:
                fitted.append(_Unit(s, e, False, sentence_count))
                continue
            for ws, we in _token_windows(text, s, e, tokenizer, max_tokens):
                fitted.append(_Unit(ws, we, False, tokenizer.count([text[ws:we]])[0]))
    return fitted


def _paragraph_refs(text: str, unit: _Unit) -> list[str]:
    segment = text[unit.start : unit.end]
    bracket = _BRACKET_PARAGRAPH.match(segment)
    if bracket:
        return [bracket.group(1)]
    numbered = _NUMBERED_PARAGRAPH.match(segment)
    if numbered and unit.tokens >= _NUMBERED_PARAGRAPH_MIN_TOKENS:
        return [numbered.group(1)]
    return []


def _pack(text: str, units: list[_Unit], target_tokens: int) -> list[_Chunk]:
    chunks: list[_Chunk] = []
    current: _Chunk | None = None
    section: str | None = None
    for unit in units:
        if unit.is_heading:
            section = " ".join(text[unit.start : unit.end].split()).rstrip(":")
        starts_new = (
            current is None or unit.is_heading or current.tokens + unit.tokens > target_tokens
        )
        if starts_new:
            if current is not None:
                chunks.append(current)
            current = _Chunk(unit.start, unit.end, unit.tokens, section)
        else:
            assert current is not None
            current.end = unit.end
            current.tokens += unit.tokens
        current.paragraph_refs.extend(_paragraph_refs(text, unit))
    if current is not None:
        chunks.append(current)
    return chunks


# Chunks smaller than this (stray page numbers, back-to-back headings) are merged into a
# neighbour when the result still fits the budget.
_MIN_CHUNK_TOKENS = 30


def _merge_small(chunks: list[_Chunk], max_tokens: int) -> list[_Chunk]:
    merged: list[_Chunk] = []
    for chunk in chunks:
        previous = merged[-1] if merged else None
        if previous is not None and previous.tokens < _MIN_CHUNK_TOKENS:
            if previous.tokens + chunk.tokens <= max_tokens:
                # Absorb the small chunk into this one; this one's heading label wins.
                chunk.start = previous.start
                chunk.tokens += previous.tokens
                chunk.paragraph_refs = previous.paragraph_refs + chunk.paragraph_refs
                merged[-1] = chunk
                continue
        if previous is not None and chunk.tokens < _MIN_CHUNK_TOKENS:
            if previous.tokens + chunk.tokens <= max_tokens:
                previous.end = chunk.end
                previous.tokens += chunk.tokens
                previous.paragraph_refs.extend(chunk.paragraph_refs)
                continue
        merged.append(chunk)
    return merged


def _enforce_max(
    text: str, chunks: list[_Chunk], tokenizer: Tokenizer, max_tokens: int
) -> list[_Chunk]:
    """Recount each chunk as a whole and split any that exceed the hard limit."""
    counts = tokenizer.count([text[c.start : c.end] for c in chunks])
    result: list[_Chunk] = []
    for chunk, count in zip(chunks, counts, strict=True):
        if count <= max_tokens:
            chunk.tokens = count
            result.append(chunk)
            continue
        window = max_tokens
        while True:
            pieces = _token_windows(text, chunk.start, chunk.end, tokenizer, window)
            piece_counts = tokenizer.count([text[s:e] for s, e in pieces])
            if max(piece_counts) <= max_tokens:
                break
            window -= max(1, max_tokens // 20)
        for (s, e), piece_count in zip(pieces, piece_counts, strict=True):
            result.append(_Chunk(s, e, piece_count, chunk.section_label, chunk.paragraph_refs))
    return result


def _page_bounds(
    source: SourceText, page_starts: list[int], start: int, end: int
) -> tuple[int | None, int | None]:
    if source.page_reference_status is not PageReferenceStatus.VERIFIED:
        return None, None
    first = source.pages[bisect.bisect_right(page_starts, start) - 1].page_index
    last = source.pages[bisect.bisect_right(page_starts, end - 1) - 1].page_index
    return first, last


def chunk_source(
    source: SourceText, tokenizer: Tokenizer, *, target_tokens: int, max_tokens: int
) -> list[ChunkDraft]:
    if target_tokens > max_tokens:
        raise ValueError("target_tokens must not exceed max_tokens")
    if source.page_reference_status is PageReferenceStatus.VERIFIED and any(
        page.page_index is None for page in source.pages
    ):
        raise ValueError("verified page references need a page_index on every page")
    text = source.text
    page_starts: list[int] = []
    offset = 0
    for page in source.pages:
        page_starts.append(offset)
        offset += len(page.text) + len(PAGE_SEPARATOR)

    units = _fit_units(text, _blocks(text), tokenizer, max_tokens)
    packed = _merge_small(_pack(text, units, target_tokens), max_tokens)
    chunks = _enforce_max(text, packed, tokenizer, max_tokens)

    drafts: list[ChunkDraft] = []
    for ordinal, chunk in enumerate(chunks):
        content = text[chunk.start : chunk.end]
        page_start, page_end = _page_bounds(source, page_starts, chunk.start, chunk.end)
        drafts.append(
            ChunkDraft(
                ordinal=ordinal,
                content=content,
                char_start=chunk.start,
                char_end=chunk.end,
                token_count=chunk.tokens,
                section_label=chunk.section_label,
                paragraph_refs=list(dict.fromkeys(chunk.paragraph_refs)),
                page_start=page_start,
                page_end=page_end,
                page_reference_status=source.page_reference_status,
                content_hash=sha256_text(content),
            )
        )
    return drafts
