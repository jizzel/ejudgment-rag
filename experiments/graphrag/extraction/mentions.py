"""References: a case name, its citations, or both, as one mention of an authority.

``Knudsen v Knudsen [1976] 1 GLR 204`` is one reference with a name and a report
citation; ``[1971] 1 GLR 242`` alone is a reference with only a citation. Parallel
citations (``[2011] 1 SCGLR 466; [2011] GHASC 3``) stay with the same reference.

Each reference also carries the signals that single out a decision (identifiers, stage
words, an explicit judgment date; ``extraction.identifiers``), read from the reference and
the text after it up to the next reference, and two flags for captions: whether caption
markers surround it (party-role labels, "----", "Represented by", page headers) and whether
a citing cue ("in", "see", "case of") comes right before it.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from experiments.graphrag.extraction.case_names import VERSION as CASE_NAMES_VERSION
from experiments.graphrag.extraction.case_names import CaseName, find_case_names, significant_words
from experiments.graphrag.extraction.citations import VERSION as CITATIONS_VERSION
from experiments.graphrag.extraction.citations import Citation, find_citations
from experiments.graphrag.extraction.identifiers import VERSION as IDENTIFIERS_VERSION
from experiments.graphrag.extraction.identifiers import decision_date, identifiers, stages

VERSION = "mentions-v4"
EXTRACTOR_VERSIONS = {
    "citations": CITATIONS_VERSION,
    "case_names": CASE_NAMES_VERSION,
    "identifiers": IDENTIFIERS_VERSION,
    "mentions": VERSION,
}

ReferenceKind = Literal[
    "neutral",  # has a neutral citation (with or without a name)
    "name_with_report",  # a case name followed by a law-report citation
    "name_only",  # a case name, with no citation or only an unclassified one
    "report_only",
    "unclassified_only",  # only a bracketed citation of an unknown series or court
]

# Between a name and its citation: spaces, a comma or full stop, and at most two
# parentheses or identifier phrases such as a suit number, stage or communication number
# ("Fuseini v. Rep. (J4/32/2014) [2018] GHASC 28", "Ajavon v. Benin (provisional measures )
# (2021) 5 AfCLR 150", "Media Rights Agenda v. Nigeria Communication 224/98 (2000) AHRLR 262").
_NAME_GAP = re.compile(
    r"[\s,.]*(?:(?:\([^()\[\]]{0,60}\)|(?i:(?:comm(?:unication)?|app(?:lication)?|suit)\.?\s*"
    r"(?:nos?\.?\s*)?[\w/-]{1,20}))[\s,.]*){0,2}"
)
SIGNAL_WINDOW = 160
# Caption and running-header markers. Party-role labels anywhere near the reference
# ("PLAINTIFF/RESPONDENT/APPELLANT", "2ND PLAINTIFF/APPLICANT"), "Represented by", and
# header shapes: "Page 27 of 33", or a page number directly before the name ("pg. 18 X v Y",
# "2 | X v Y") or "– JUDGMENT" directly after it. Pinpoints such as "at page 6" or
# "@ pg. 72 para 26; X v Y" are not headers.
_CAPTION_AROUND = re.compile(
    r"(?<![A-Za-z])(?:\d+(?:ST|ND|RD|TH)\s+)?(?:PLAINTIFFS?|DEFENDANTS?|APPELLANTS?|RESPONDENTS?"
    r"|APPLICANTS?|PETITIONERS?|COMPLAINANTS?)(?![a-z])"
    r"|(?i:\b(?:plaintiff|defendant|appellant|respondent|applicant)s?\s*/\s*"
    r"(?:plaintiff|defendant|appellant|respondent|applicant))"
    r"|(?i:\brepresented\s+by\b)|(?i:\bpage\s+\d+\s+of\s+\d+)"
    r"|(?i:composition\s+of\s+the\s+court|\bcoram\b|\bbefore\s*:)"
)
_PAGE_OF = re.compile(r"(?i:\bpage\s+\d+\s+of\s+\d+)")
_HEADER_BEFORE = re.compile(r"(?:(?i:\bpg\.?)\s*\d+|(?:^|\s)\d{1,3}\s*\|)\s*$")
_HEADER_AFTER = re.compile(r"^\s*[-–—]\s*(?:JUDGMENT|RULING)\b")
_CUE = re.compile(
    r"\b(?:in|see|case\s+of|cases\s+of|cited|citing|per|followed|applied|relied\s+on"
    r"|according\s+to|authority\s+of|decision\s+in|also)[\s,:]*$",
    re.IGNORECASE,
)
# Between parallel citations.
_CITATION_GAP = re.compile(r"[\s,;]*(?:and\s+)?")


@dataclass(frozen=True)
class Reference:
    start: int  # offsets in the scanned text
    end: int
    name: CaseName | None
    citations: tuple[Citation, ...]
    identifiers: frozenset[str] = field(default_factory=frozenset)
    stages: frozenset[str] = field(default_factory=frozenset)
    decision_date: date | None = None
    caption_marker: bool = False  # caption or running-header markers around it
    cue_before: bool = False  # a citing cue ("in", "see", "case of") right before it
    # For a citation without a linked name: the significant words on each side of a case
    # name just before it that could not be linked ("Adjei v Ak werter [2023] GHAHC 31",
    # split by OCR). Such a name must still agree with the citation's target.
    adjacent_sides: tuple[frozenset[str], frozenset[str]] | None = None

    @property
    def kind(self) -> ReferenceKind:
        if any(c.kind == "neutral" for c in self.citations):
            return "neutral"
        if self.name is not None:
            return "name_with_report" if self.report_years is not None else "name_only"
        if any(c.kind == "law_report" for c in self.citations):
            return "report_only"
        return "unclassified_only"

    @property
    def neutral(self) -> Citation | None:
        return next((c for c in self.citations if c.kind == "neutral"), None)

    @property
    def report_years(self) -> tuple[int, int] | None:
        """Year span of the first law-report citation, if any."""
        report = next((c for c in self.citations if c.kind == "law_report"), None)
        return (report.year, report.year_end) if report else None


EVIDENCE_LIMIT = 300
# A sentence ends at . ! ? or ; followed by space and a capital, digit, quote or bracket, or
# at a paragraph break; not after an abbreviation used in citations ("v.", "No.", "Ltd.").
_BOUNDARY = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"“'(\[])|\n\s*\n")
_ABBREVIATION_END = re.compile(
    r"\b(?:[a-z]|v|vs|vrs|no|nos|ltd|co|corp|inc|bros|ja|jsc|cj|mr|mrs|dr|pp|para|paras|ss"
    r"|cf|e\.g|i\.e|art|sec|ch|vol|ed|eds|app|comm|op|cit|al|st)\.$",
    re.IGNORECASE,
)


def _boundaries(text: str) -> list[int]:
    """Offsets where a new sentence starts."""
    return [
        m.end()
        for m in _BOUNDARY.finditer(text)
        if not _ABBREVIATION_END.search(text[max(0, m.start() - 8) : m.start()])
    ]


def evidence_span(text: str, start: int, end: int, limit: int = EVIDENCE_LIMIT) -> tuple[int, int]:
    """The sentence (at most ``limit`` characters each way) that holds a reference: the
    evidence an edge points to, wider than the reference itself."""
    low, high = max(0, start - limit), min(len(text), end + limit)
    before = [b for b in _boundaries(text[low:start]) if b < start - low]
    begin = low + before[-1] if before else low
    after = _boundaries(text[end:high])
    finish = end + after[0] if after else high
    return begin, len(text[:finish].rstrip()) if finish > end else end


def _chain(text: str, first: int, citations: list[Citation]) -> list[int]:
    """Indices of ``citations[first]`` and the parallel citations directly after it."""
    chain = [first]
    while chain[-1] + 1 < len(citations):
        current, following = citations[chain[-1]], citations[chain[-1] + 1]
        if not _CITATION_GAP.fullmatch(text, current.end, following.start):
            break
        chain.append(chain[-1] + 1)
    return chain


def find_references(text: str) -> list[Reference]:
    citations = find_citations(text)
    references: list[Reference] = []
    used: set[int] = set()
    for name in find_case_names(text, barriers=[c.end for c in citations]):
        follower = next(
            (i for i, c in enumerate(citations) if c.start >= name.end and i not in used), None
        )
        chain: list[int] = []
        if follower is not None and _NAME_GAP.fullmatch(text, name.end, citations[follower].start):
            chain = _chain(text, follower, citations)
        used.update(chain)
        cited = tuple(citations[i] for i in chain)
        references.append(
            Reference(
                start=name.start,
                end=cited[-1].end if cited else name.end,
                name=name,
                citations=cited,
            )
        )
    index = 0
    while index < len(citations):
        if index in used:
            index += 1
            continue
        chain = _chain(text, index, citations)
        chain = [i for i in chain if i not in used]
        cited = tuple(citations[i] for i in chain)
        references.append(Reference(cited[0].start, cited[-1].end, None, cited))
        used.update(chain)
        index = chain[-1] + 1
    references.sort(key=lambda r: r.start)
    return [_with_signals(text, r, references) for r in references]


def _with_signals(text: str, reference: Reference, every: list[Reference]) -> Reference:
    following = min((r.start for r in every if r.start >= reference.end), default=len(text))
    stop = min(reference.end + SIGNAL_WINDOW, following)
    # Signals end with the sentence: a footnote's next entry ("… § 29. 3 Application No.
    # 005/2013 …") belongs to another reference.
    after = _boundaries(text[reference.end : stop])
    if after:
        stop = reference.end + after[0]
    window = text[reference.start : stop]
    # Identifiers may also come first, in footnote lists: "Communications 64/92, 68/92 and
    # 78/92 – Achuthan … v Malawi (1994) ACHPR 7". Read back to the start of the sentence
    # or the end of the previous reference, whichever is nearer.
    previous = max((r.end for r in every if r.end <= reference.start), default=0)
    low = max(previous, reference.start - SIGNAL_WINDOW)
    before = _boundaries(text[low : reference.start])
    leading = text[low + before[-1] if before else low : reference.start]
    around = text[max(0, reference.start - 25) : reference.end + 25]
    return Reference(
        start=reference.start,
        end=reference.end,
        name=reference.name,
        citations=reference.citations,
        identifiers=identifiers(window) | identifiers(leading),
        stages=stages(window),
        decision_date=decision_date(window),
        caption_marker=bool(
            _CAPTION_AROUND.search(around)
            or _HEADER_BEFORE.search(text[max(0, reference.start - 12) : reference.start])
            or _HEADER_AFTER.search(text[reference.end : reference.end + 15])
            # A running header's page count can follow its suit number and date:
            # "KOHL V. CBG SUIT NO.:H1/95/2021 DATED 28TH NOVEMBER, 2022 Page 26 of 28".
            or _PAGE_OF.search(text[reference.end : reference.end + 80])
        ),
        cue_before=bool(_CUE.search(text[max(0, reference.start - 40) : reference.start])),
        adjacent_sides=None if reference.name else _adjacent_sides(leading),
    )


_ADJACENT_SEPARATOR = re.compile(r"\s(?:versus|v\s?rs|vs|v)\.?\s", re.IGNORECASE)
ADJACENT_SIDE_TOKENS = 6


def _adjacent_sides(leading: str) -> tuple[frozenset[str], frozenset[str]] | None:
    """Words either side of the last "v" in the text just before a citation, if any."""
    separators = list(_ADJACENT_SEPARATOR.finditer(leading))
    if not separators:
        return None
    last = separators[-1]
    left = leading[: last.start()].split()[-ADJACENT_SIDE_TOKENS:]
    right = leading[last.end() :].split()[:ADJACENT_SIDE_TOKENS]
    return significant_words(left), significant_words(right)
