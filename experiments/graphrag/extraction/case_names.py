"""Case-name references such as ``Knudsen v Knudsen`` or ``REPUBLIC VRS NSOR``.

Party sides are delimited the way query parsing does it (``v``, ``vs``, ``vrs``,
``versus``; ``ejudgment.retrieval.query``), but in running text the extent of each side
is unknown. So each side is extended over at most ``MAX_SIDE_TOKENS`` name-like tokens
and stops at a citation bracket, sentence punctuation, a lowercase word that is not a
connector, or a word such as "case" or "see". The span is only for display and audit:
resolution uses the significant word of each side *nearest to the separator*, which is
the party name even when a side was over-extended in all-caps text, together with
each side's set of significant words.

v2 (after the first edge audit): sides also stop at document labels ("JUDGMENT", "Pg",
"Communication", "Referred") and at an identifier ("308/2005-"); a short bracketed word
stays inside a name ("Mondial Veneer (Gh) Ltd"); a side may begin with a digit
("2Others"); and the right side's *last* significant word is kept as its anchor (the
surname: "Stephen Mensah").
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

VERSION = "case-names-v10"

MAX_SIDE_TOKENS = 12  # long institutional names: "Zimbabwe Lawyers for Human Rights & …"
_WINDOW = 160

# "v rs" occurs in extracted text where a space crept into "vrs".
_SEPARATOR = re.compile(r"(?<=[\w.)&'’])\s+(?:versus|v\s?rs|vs|v)\.?\s+(?=[\w\"'(])", re.IGNORECASE)
_TOKEN = re.compile(r"\S+")
# Words that end a side however they are capitalised (all-caps judgments are common).
_STOP = frozenset(
    "IN SEE CASE CASES CITED PER HELD WHERE WHICH THAT ALSO BY TO FROM ON AS IS WAS WERE "
    "AT WHEN WHILE THIS THESE THOSE HIS HER ITS THEIR SAID SUPRA CF VIZ "
    # document labels next to captions and running headers
    "JUDGMENT RULING PG PAGE PARA PARAGRAPH REFERRED REPORTED DELIVERED CORAM COMPOSITION "
    "COMM COMMUNICATION APPLICATION SUIT "
    # descriptors after a party: "– Deceased (Substituted by …)"
    "DECEASED SUBSTITUTED".split()
)
# Lowercase words allowed inside a side ("Commissioner of Police", "ex parte").
_CONNECTORS = frozenset("of and & the ex parte de la le du da von van for".split())
_ABBREVIATIONS = frozenset("LTD CO ANOR ANR ORS BROS INC CORP NO ST MR MRS DR".split())
_SIGNIFICANT = re.compile(r"[A-Z0-9]{3,}")
# Not a party's name: company forms and "and others".
NOT_SIGNIFICANT = frozenset(
    "AND ANOR ANR ORS OTHERS ANOTHER THE OF EX PARTE FOR IN ON AT BY "
    "LTD LIMITED COMPANY INC PLC CORP COMM COMMUNICATION APPLICATION AKA ALIAS".split()
)


@dataclass(frozen=True)
class CaseName:
    text: str  # verbatim span, both sides and the separator
    start: int
    end: int
    left: str
    right: str
    left_word: str  # significant word of each side nearest to the separator
    right_word: str
    left_words: frozenset[str]  # all significant words of each side
    right_words: frozenset[str]
    # Surname of the right side's first party: the last significant word before "&", "and"
    # or a comma ("Stephen Mensah"; "Shell Ghana Ltd & Fraga Oil Ltd" -> GHANA).
    right_anchor: str
    # "Republic v High Court, Accra; Ex parte Allgate": the applicant identifies the case.
    ex_parte_word: str | None = None
    # The applicant's surname, tried only when ``ex_parte_word`` (its first word) matches no
    # title: "Ex parte Benjamin Duffour" is titled "Ex Parte: Duffour".
    ex_parte_surname: str | None = None
    # All significant words of the applicant (its first party): a surname fallback may only
    # match a title whose applicant names nothing else ("Hansen Kwadwo Koduah" is not
    # "Tweneboah Koduah").
    ex_parte_words: frozenset[str] = frozenset()


def _bare(token: str) -> str:
    return token.strip("\"'“”‘’(),;:")


def _ends_sentence(token: str) -> bool:
    if token.endswith((";", ":", "!", "?")):
        return True
    if token.endswith("."):
        return _bare(token).rstrip(".").upper() not in _ABBREVIATIONS
    return False


# A dash alone or leading a word continues a hyphenated name that OCR spaced out
# ("Attorney -General", "Baffoe – Bonnie", "De -Graft"): one word, then the side ends
# unless another party follows. Descriptors after a dash are not names ("Gyamfua –
# Deceased": ``_STOP``), and "Ex -parte" never ends a side.
_DASHES = "-–—"
# After a continued word only another party may follow ("Attorney -General & Ors").
_AFTER_CONTINUATION = frozenset({"&", "AND"})


def _continues(token: str) -> bool:
    """A dash alone, or a word a dash leads ("-General"); not "-parte"."""
    bare = _bare(token)
    return bool(bare) and bare[0] in _DASHES and bare.lstrip(_DASHES).lower() != "parte"


def _name_like(token: str) -> bool:
    bare = _bare(token)
    if bare and all(ch in _DASHES for ch in bare):
        return True
    bare = bare.lstrip(_DASHES)
    if not bare:
        return False
    if bare.upper().rstrip(".") in _STOP:
        return False
    return bare[0].isupper() or bare[0].isdigit() or bare == "&" or bare.lower() in _CONNECTORS


# Abbreviations courts use for a party, read as the full word ("Fuseini v. Rep.").
_ALIASES = {"REP": "REPUBLIC", "REPUB": "REPUBLIC"}


def token_words(token: str) -> list[str]:
    """Significant words of one token: three or more letters or digits, leading digits
    dropped ("2Others" is "OTHERS"), company forms and "and others" left out."""
    words = (w.lstrip("0123456789") for w in _SIGNIFICANT.findall(token.upper()))
    return [_ALIASES.get(w, w) for w in words if len(w) >= 3 and w not in NOT_SIGNIFICANT]


def significant_words(words: Sequence[str]) -> frozenset[str]:
    return frozenset(w for token in words for w in token_words(token))


def _significant(words: list[str], *, from_end: bool) -> str | None:
    """The first significant word, reading from the separator outwards."""
    ordered = list(reversed(words)) if from_end else words
    for word in ordered:
        found = token_words(word)
        if found:
            return found[-1] if from_end else found[0]
    return None


def _identifier(token: str) -> bool:
    """A number such as "308/2005-" or "J4/43/2013", or a paragraph sign ("§ 158", also as
    mojibake "Â§"), belongs to a label or pinpoint, not a name."""
    return ("/" in token and any(ch.isdigit() for ch in token)) or "§" in token or "¶" in token


_PARTY_BREAK = {"&", "AND"}
_ALIAS = {"AKA", "A.K.A", "ALIAS", "@"}


def _first_party(tokens: list[str]) -> list[str]:
    """The tokens of the first party on a side ("Shell Ghana Ltd & Fraga Oil Ltd")."""
    party: list[str] = []
    for token in tokens:
        if _bare(token).upper().rstrip(".") in _PARTY_BREAK:
            break
        party.append(token)
        if token.endswith(","):
            break
    return party or tokens


def _before_alias(tokens: list[str]) -> list[str]:
    """A left side without its trailing alias ("Kwaku Frimpong aka Iboman" -> "… Frimpong")."""
    for i, token in enumerate(tokens):
        if _bare(token).upper().rstrip(".") in _ALIAS and i > 0:
            return tokens[:i]
    return tokens


def _left_side(text: str, end: int, floor: int = 0) -> tuple[int, list[str]] | None:
    start = max(0, end - _WINDOW, floor)
    window = text[start:end]
    # Nothing before a citation bracket or a paragraph break belongs to the name.
    cut = max(window.rfind("["), window.rfind("]"), window.rfind("\n\n"))
    tokens = [m for m in _TOKEN.finditer(window) if m.start() > cut]
    side: list[re.Match[str]] = []
    for index, match in enumerate(reversed(tokens)):
        token = match.group(0)
        if side and _continues(side[-1].group(0)):
            # "Attorney -General v X": the word before the continued one completes it.
            side.append(match)
            break
        # Further out, a dashed word ends the side: a forename the title may lack
        # ("REV. DE -GRAFT SEFA & Others v BANK OF GHANA" is titled "Rev. Sefa and Others").
        # At the start of a line the dash is a list bullet and its word is the party's:
        # "…SCGLR 601\n-FRIMPONG A.K.A IBOMAN V REPUBLIC".
        if index > 0 and _continues(token):
            if window[: match.start()].rstrip(" \t").endswith("\n") and _name_like(token):
                side.append(match)
            break
        if not _name_like(token) or _identifier(token):
            break
        # A bare number stays only as "& 4 Ors"; otherwise it is a footnote marker.
        if _bare(token).isdigit() and not (
            side and _bare(side[-1].group(0)).upper().rstrip(".") in {"ORS", "OR", "OTHERS"}
        ):
            break
        if index > 0 and (_ends_sentence(token) or token.endswith(",")):
            break
        side.append(match)
        if len(side) == MAX_SIDE_TOKENS:
            break
    side.reverse()
    # "of Commissioner" -> "Commissioner"; a footnote number before the name is not part of it.
    while side and (
        _bare(side[0].group(0)).lower() in _CONNECTORS
        or not any(ch.isalpha() for ch in side[0].group(0))  # "13", "2°"
    ):
        side.pop(0)
    if not side or not any(_bare(m.group(0))[:1].isupper() for m in side):
        return None
    return start + side[0].start(), [m.group(0) for m in side]


def _right_side(text: str, begin: int) -> tuple[int, list[str]] | None:
    window = text[begin : begin + _WINDOW]
    # A side ends at a citation or a bracketed suit number: "OWUSU & ANOR[1967]", "(B7/91/23)",
    # but not at a short bracketed word inside the name: "Mondial Veneer (Gh) Ltd".
    cut = re.search(r"\[|\((?![A-Za-z.]{1,8}\)\s+[A-Z])|\n\n", window)
    if cut:
        window = window[: cut.start()]
    side: list[re.Match[str]] = []
    continued = False  # a hyphenated word was just completed
    for match in _TOKEN.finditer(window):
        token = match.group(0)
        if continued and _bare(token).upper() not in _AFTER_CONTINUATION:
            break  # "Attorney -General Writ No.", "Attorney -General S. C.": the name ends
        if not _name_like(token) or _identifier(token):
            break
        side.append(match)
        dash_alone = bool(_bare(token)) and all(ch in _DASHES for ch in _bare(token))
        after_dash = len(side) > 1 and all(ch in _DASHES for ch in _bare(side[-2].group(0)))
        # "-General& Anor": a party break glued to the word lets the next party follow.
        continued = ((_continues(token) and not dash_alone) or after_dash) and not token.endswith(
            "&"
        )
        if _ends_sentence(token) or token.endswith(",") or len(side) == MAX_SIDE_TOKENS:
            break
    while side and (
        _bare(side[-1].group(0)).lower() in _CONNECTORS
        or all(ch in _DASHES for ch in _bare(side[-1].group(0)))
    ):
        side.pop()
    # A trailing suit label is not part of the name: "AKWASI MENSAH CA NO, J4/45/2019".
    while side and _bare(side[-1].group(0)).upper().rstrip(".") in {"NO", "NOS"}:
        side.pop()
        if side and _bare(side[-1].group(0)).upper().rstrip(".") in {"CA", "SC", "HC", "SUIT"}:
            side.pop()
    if not side or not _bare(side[0].group(0))[:1].isupper():
        return None
    last = side[-1].group(0).rstrip(",;:-–—")
    if last.endswith(".") and _bare(last).rstrip(".").upper() not in _ABBREVIATIONS:
        last = last.rstrip(".")
    return begin + side[-1].start() + len(last), [m.group(0) for m in side]


# "; Ex parte X", also after a place, a bracketed division or further respondents:
# "Republic v High Court, (Commercial Division) Accra; Ex -parte Attorney-General",
# "The Republic v Bank of Ghana, The Governor (Bank of Ghana) and 4 others Ex-parte Duffour".
_EX_PARTE = re.compile(
    # Each token must end at a separator, so a word can't be split many ways (backtracking).
    r"[\s,]*(?:(?:\([^()]{0,40}\)|[A-Za-z0-9][\w.]*)[\s,;]+){0,8}[;,]?\s*ex[\s\-–—]*parte[:,]?\s+",
    re.IGNORECASE,
)


def _ex_parte(text: str, begin: int) -> tuple[int, str, str | None, frozenset[str]] | None:
    """Extends a side over a following "; Ex parte NAME", returning its end, the applicant's
    first significant word and its surname ("Ampong Alias Akrufa Krukoko": AMPONG)."""
    match = _EX_PARTE.match(text, begin)
    if match is None:
        return None
    applicant = _right_side(text, match.end())
    if applicant is None:
        return None
    word = _significant(applicant[1], from_end=False)
    party = _before_alias(_first_party(applicant[1]))
    surname = _significant(party, from_end=True)
    return (applicant[0], word, surname, significant_words(party)) if word else None


def find_case_names(text: str, barriers: Sequence[int] = ()) -> list[CaseName]:
    """Every ``A v B`` reference in ``text`` whose sides each have a significant word.

    ``barriers``: offsets a left side may not extend back over, e.g. the ends of earlier
    citations ("(2012) 1 SCGLR 417 COLEMAN v TRIPOLLEN").
    """
    found: list[CaseName] = []
    ends = sorted(barriers)
    for separator in _SEPARATOR.finditer(text):
        floor = max((e for e in ends if e <= separator.start()), default=0)
        left = _left_side(text, separator.start(), floor)
        right = _right_side(text, separator.end())
        if left is None or right is None:
            continue
        left_word = _significant(left[1], from_end=True)
        right_word = _significant(right[1], from_end=False)
        right_anchor = _significant(_first_party(right[1]), from_end=True)
        left_word = _significant(_before_alias(left[1]), from_end=True) or left_word
        if left_word is None or right_word is None or right_anchor is None:
            continue
        start, end = left[0], right[0]
        ex_parte = _ex_parte(text, end)
        if ex_parte is not None:
            end = ex_parte[0]
        found.append(
            CaseName(
                text=text[start:end],
                start=start,
                end=end,
                left=" ".join(left[1]),
                right=" ".join(right[1]).rstrip(",;:"),
                left_word=left_word,
                right_word=right_word,
                left_words=significant_words(left[1]),
                right_words=significant_words(right[1]),
                right_anchor=right_anchor,
                ex_parte_word=ex_parte[1] if ex_parte else None,
                ex_parte_surname=ex_parte[2] if ex_parte else None,
                ex_parte_words=ex_parte[3] if ex_parte else frozenset(),
            )
        )
    return found
