"""Signals near a reference that identify *which decision* is meant, not just which parties.

Party names identify a litigation (a case family); one family can hold several decisions:
a provisional-measures order, a merits judgment, reparations, a review. These signals,
read from a reference and the text right after it, single out the decision:

- **identifiers**: application, communication and suit numbers (``Application No.
  008/2020``, ``Communication 224/98``, ``ECW/CCJ/APP/11/18``, ``J4/43/2013``),
  normalised so that ``H2/17/19`` and ``H2/17/2019`` are equal;
- **stages**: words naming the procedural stage (merits, reparations, provisional
  measures, review, interpretation, jurisdiction/admissibility);
- **decision date**: an explicit judgment date ("Judgment of 23 June 2022", "delivered
  on 28 June 2007", or a date in brackets right after the name).

The same functions read a corpus judgment's own citation and title, so a reference and a
candidate are compared in the same terms.
"""

import re
from datetime import date

VERSION = "identifiers-v3"

_MONTHS = {
    m: i
    for i, m in enumerate(
        "january february march april may june july august september october november "
        "december".split(),
        start=1,
    )
}
_NUMBERS = r"((?:\d{1,4}\s*(?:/|\s+of\s+)\s*\d{2,4}(?:\s*(?:,|;|and|&)\s*)?)+)"
# No word boundary before the label: text that lost its spaces glues it to a footnote
# number ("9Communications64/92,68/92and78/92").
_APPLICATION = re.compile(
    r"(?<![A-Za-z])App(?:lication)?s?\.?\s*(?:Nos?\.?\s*)?" + _NUMBERS, re.IGNORECASE
)
_COMMUNICATION = re.compile(
    r"(?<![A-Za-z])Comm(?:unication)?s?\.?\s*(?:Nos?\.?\s*)?" + _NUMBERS, re.IGNORECASE
)
_PAIR = re.compile(r"(\d{1,4})\s*(?:/|\s+of\s+)\s*(\d{2,4})", re.IGNORECASE)
_ECOWAS = re.compile(
    r"ECW\s*/\s*CCJ\s*/\s*(APP|JUD)\s*/\s*(\d{1,4})\s*/\s*(\d{2,4})", re.IGNORECASE
)
# Ghanaian suit numbers: a letter prefix, a number and a year (J4/43/2013, B7/91/23).
_SUIT = re.compile(r"(?<![\w/])([A-Z]{1,3}\d{0,2})\s*/\s*(\d{1,5})\s*/\s*(\d{2,4})(?![\w/])")
# "11 February 2021", "11th day of February, 2021".
_DATE = (
    r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?("
    + "|".join(_MONTHS)
    + r")\s*,?\s+((?:19|20)\d\d)"
)
# Only dates that name *the decision*: "Judgment of …", "delivered on (the) …", "dated …",
# or a bracketed date ("(09 May, 2018)", "(21 September 2018)").
_DECISION_DATE = re.compile(
    r"(?:\b(?:judgment|ruling|decision|order)\s+(?:of|dated|delivered\s+on)\s+(?:the\s+)?"
    r"|\bdelivered\s+on\s+(?:the\s+)?|\bdated\s+(?:the\s+)?|\()" + _DATE,
    re.IGNORECASE,
)
STAGES = {
    "provisional_measures": re.compile(r"provisional\s+measure", re.IGNORECASE),
    "reparations": re.compile(r"\breparation", re.IGNORECASE),
    "review": re.compile(r"\b(?:review|revision)\b", re.IGNORECASE),
    "interpretation": re.compile(r"\binterpretation\b", re.IGNORECASE),
    "jurisdiction": re.compile(
        r"\b(?:admissibility|jurisdiction|preliminary objection)", re.IGNORECASE
    ),
    "merits": re.compile(r"\bmerits\b", re.IGNORECASE),
}
# A decision is the case's main judgment when it names no stage or includes the merits
# ("merits and reparations"); otherwise it is a secondary decision (an order, a reparations
# or admissibility ruling, a review), which an unlabelled reference is not taken to mean.
MAIN_STAGE = "merits"
# A reference to a jurisdiction/admissibility ruling may mean an unlabelled corpus decision:
# a ruling of inadmissibility is often the case's final decision (and titled without a stage).
FINAL_STAGES = frozenset({MAIN_STAGE, "jurisdiction"})


def _year(raw: str) -> int:
    return int(raw[-2:])


def identifiers(text: str) -> frozenset[str]:
    found: set[str] = set()
    for pattern, kind in ((_APPLICATION, "APP"), (_COMMUNICATION, "COMM")):
        for match in pattern.finditer(text):
            for number, year in _PAIR.findall(match.group(1)):
                found.add(f"{kind} {int(number)}/{_year(year):02d}")
    for kind, number, year in _ECOWAS.findall(text):
        found.add(f"ECW-{kind.upper()} {int(number)}/{_year(year):02d}")
    without_ecowas = _ECOWAS.sub(" ", text)
    for prefix, number, year in _SUIT.findall(without_ecowas):
        if prefix.upper() in {"APP", "JUD", "CCJ", "ECW"}:
            continue
        found.add(f"SUIT {prefix.upper()}/{int(number)}/{_year(year):02d}")
    return frozenset(found)


# Stage words count only where they label a decision: in brackets ("(merits and
# reparations)", "(Order for Provisional Measures)") or after "judgment/ruling/order/decision
# on|for" ("Judgment on Reparations"). In running prose they are ordinary words
# ("the interpretation of Article 2", "on review").
_STAGE_LABEL = re.compile(
    r"\(([^()]{0,80})\)|\b(?:judgment|ruling|order|decision)s?\s+(?:on|for)\s+(?:the\s+)?"
    r"([a-z ]{0,40})",
    re.IGNORECASE,
)


def stages(text: str) -> frozenset[str]:
    labels = " ".join(a or b for a, b in _STAGE_LABEL.findall(text))
    return frozenset(name for name, pattern in STAGES.items() if pattern.search(labels))


def decision_date(text: str) -> date | None:
    match = _DECISION_DATE.search(text)
    if match is None:
        return None
    day, month, year = match.groups()
    try:
        return date(int(year), _MONTHS[month.lower()], int(day))
    except ValueError:
        return None


def _main(stage_set: frozenset[str]) -> bool:
    return not stage_set or MAIN_STAGE in stage_set


def stages_compatible(reference: frozenset[str], target: frozenset[str]) -> bool:
    """Could a reference naming ``reference`` stages mean a decision with ``target`` stages?

    Both labelled: they must share a stage. An unlabelled reference means a main judgment.
    A labelled reference to an unlabelled decision must name the merits or jurisdiction:
    "(reparations)" does not mean the merits judgment.
    """
    if reference and target:
        return bool(reference & target)
    if not reference:
        return _main(target)
    return bool(reference & FINAL_STAGES)
