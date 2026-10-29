"""Bracketed citations in judgment text: neutral citations, law-report citations, the rest.

The two share a shape. ``[2019] GHASC 12`` is a neutral citation; ``[1981] GLR 752`` and
``[1992] 1 GLR 123`` are law reports. They are told apart by the court or series token,
never guessed: a token in neither list is counted as ``unclassified``.

A neutral citation can be resolved by exact lookup. A law-report citation cannot: the
corpus has no report-citation field, so it is profiled but never mapped to a judgment
(docs/graphrag/AGENTS.md, Phase 1 B).
"""

import re
from dataclasses import dataclass
from typing import Literal

VERSION = "citations-v2"

CitationKind = Literal["neutral", "law_report", "unclassified"]

# Courts whose judgments carry neutral citations. The first group is the corpus's own
# (court_code upper-cased); the rest are common foreign ones, recognised so that they are
# counted as neutral citations to courts outside the corpus rather than as unknown tokens.
CORPUS_COURTS = frozenset("GHASC GHACA GHAHC GHADC GHACC AFCHPR ACHPR ECOWASCJ".split())
FOREIGN_NEUTRAL_COURTS = frozenset(
    """UKSC UKHL UKPC UKUT UKFTT EWCA EWHC EWFC EWCOP IEHC IESC ZACC ZASCA NGSC NGCA KESC
    KECA UGSC TZCA ZMSC SLSC GMSC LRSC BWCA NAHCMD MWSC HCA NSWSC NSWCA SCC CSIH CSOH
    UKIPTRIB EACJ SADCT CCJ ECHR ECTHR""".split()
)
NEUTRAL_COURTS = CORPUS_COURTS | FOREIGN_NEUTRAL_COURTS
# English neutral citations add a division after the court: [2019] EWCA Civ 12.
_DIVISIONS = ("Civ", "Crim", "Admin", "Comm", "Ch", "QB", "KB", "Fam", "Pat", "TCC", "IPEC")

# Law-report series, compared without dots or spaces (G.L.R. -> GLR, All ER -> ALLER).
REPORT_SERIES = frozenset(
    # Ghana
    """GLR SCGLR GLRD GBR GMJ MLRG CCJELR JELR DLSC DLCA DLHC DLCC DLDC GHALR GR ALRCOMM"""
    # Ghana series printed with a slip: "1" read as "I" ([2011] ISCGLR 466), letters
    # transposed (SCLRG, SGLR, GRL). Counted as the report citations they are.
    """ IGLR ISCGLR SCLRG SGLR GRL"""
    # West Africa, Africa, the Commonwealth and human-rights reports
    """ WALR WACA NLR NWLR ALR EA SA LRC CHRLD AFCLR AHRLR EHRR"""
    # England
    """ AC QB KB CH WLR ALLER AER PD PROB FAM CR CRAPPR CRAPPRS LR TLR LT LJ LJQB LJKB LJCH
    ER BCLC IRLR EWLR CHD QBD APPCAS CRIMLR HARE CLR SCR""".split()
)

# Optional opening bracket character, year or year range, closing bracket, optional
# volume, series or court token(s), page or number. Whitespace may be lost in extracted
# text ([1981]GLR752), so every gap is \s*.
# A year, allowing one OCR space inside it ("[1 974]").
_YEAR = r"(?P<y1>1\s?[89]\s?\d\s?\d|2\s?0\s?\d\s?\d)"
# Between the series and the page: a part label ("GLR (Pt,II) 671") and "at page" / "page"
# ("(2013) CCJELR page 257", "(2012) 48 G. M.J at page 44").
_PAGE_PREFIX = r"(?:\s*\(\s*Pt\.?[\s,]*[IVX\d]+\s*\))?(?:\s*(?:at\s+)?(?:page|pg\.?|p\.))?"

_BRACKETED = re.compile(
    r"(?P<open>[\[(])\s*" + _YEAR + r""
    r"(?:\s*[-–/]\s*(?P<y2>\d{2,4}))?\s*[\])]"
    r"\s*(?P<volume>\d{1,2}(?!\d))?"
    r"\s*(?P<token>[A-Z][A-Za-z]{0,9}(?:\.?\s?[A-Z][A-Za-z]{0,5}\.?){0,3})"
    + _PAGE_PREFIX
    + r"\s*(?P<number>\d{1,5})(?!\d)"
)


# The same without brackets ("Ampah v The Republic 1977 2 GLR 171"). Only a known report
# series or neutral court counts here: an unbracketed year before any capitalised word
# ("1992 Constitution 19") is far too common to profile as "unclassified".
_UNBRACKETED = re.compile(
    r"(?<![\[(\d])\b(?P<y1>1[89]\d\d|20\d\d)(?P<y2>)"
    r"\s+(?P<volume>\d{1,2}(?!\d))?"
    r"\s*(?P<token>[A-Z][A-Za-z]{0,9}(?:\.?\s?[A-Z][A-Za-z]{0,5}\.?){0,3})"
    + _PAGE_PREFIX
    + r"\s*(?P<number>\d{1,5})(?!\d)"
)


@dataclass(frozen=True)
class Citation:
    kind: CitationKind
    text: str  # the matched text, verbatim
    start: int  # offsets in the scanned text
    end: int
    year: int
    year_end: int  # == year unless a range such as [2005-2006]
    token: str  # court code or report series, normalised (upper case, no dots or spaces)
    volume: int | None
    number: int  # neutral: judgment number; report: first page

    @property
    def key(self) -> str:
        """Normalised form: ``[2019] GHASC 12`` or ``[1992] 1 GLR 123``."""
        years = str(self.year) if self.year_end == self.year else f"{self.year}-{self.year_end}"
        volume = f" {self.volume}" if self.volume is not None else ""
        return f"[{years}]{volume} {self.token} {self.number}"


def _year_end(start: int, raw: str | None) -> int:
    if not raw:
        return start
    if len(raw) == 4:
        end = int(raw)
    else:  # [1995-96], [1984-86]: the century of the start year
        end = int(str(start)[: 4 - len(raw)] + raw)
    return end if start <= end <= start + 10 else start


_COURT_DIVISIONS = {
    court + division.upper(): f"{court} {division.upper()}"
    for court in FOREIGN_NEUTRAL_COURTS
    for division in _DIVISIONS
}


def _normalise_token(raw: str) -> str:
    """``G.L.R.`` -> ``GLR``, ``All ER`` -> ``ALLER``, ``EWCA Civ`` -> ``EWCA CIV``."""
    token = re.sub(r"[.\s]", "", raw).upper()
    return _COURT_DIVISIONS.get(token, token)


def _classify(token: str, volume: str | None) -> CitationKind:
    if volume is None and token.split(" ")[0] in NEUTRAL_COURTS:
        return "neutral"
    if token in REPORT_SERIES:
        return "law_report"
    return "unclassified"


def find_citations(text: str) -> list[Citation]:
    """Every bracketed citation in ``text``, in order of appearance."""
    found: list[Citation] = []
    matches = [(m, True) for m in _BRACKETED.finditer(text)]
    taken = [(m.start(), m.end()) for m, _ in matches]
    for match in _UNBRACKETED.finditer(text):
        if not any(start < match.end() and match.start() < end for start, end in taken):
            matches.append((match, False))
    for match, bracketed in sorted(matches, key=lambda item: item[0].start()):
        token = _normalise_token(match["token"])
        year = int(re.sub(r"\s", "", match["y1"]))
        kind = _classify(token, match["volume"])
        if not bracketed and kind == "unclassified":
            continue
        found.append(
            Citation(
                kind=kind,
                text=match.group(0),
                start=match.start(),
                end=match.end(),
                year=year,
                year_end=_year_end(year, match["y2"]),
                token=token,
                volume=int(match["volume"]) if match["volume"] is not None else None,
                number=int(match["number"]),
            )
        )
    return found
