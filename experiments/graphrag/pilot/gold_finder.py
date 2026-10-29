"""Gold finding for pilot questions, independent of the resolver and the graph.

    python -m experiments.graphrag.pilot.gold_finder sheet --question <id> [--anchor <uri>]
    python -m experiments.graphrag.pilot.gold_finder lookup --citation "[2012] GHASC 8"
    python -m experiments.graphrag.pilot.gold_finder import --question <id> --sheet <csv>
        [--path uri,uri,uri]

Gold must come from the source judgments, never from a system's output
(docs/graphrag/AGENTS.md rule 6). So candidates are found by plain text search over the
corpus, read-only, and a person decides:

- **incoming** (later treatment of an anchor): passages of other judgments that name both
  parties of the anchor (significant title words), or carry its neutral citation or a
  report citation the writer supplied;
- **outgoing** (what the anchor relied on): the anchor's own passages that contain a
  "v"-name or a bracketed citation, with a column for the cited case's URI (``lookup``
  helps find it by citation or party names);
- **lineage**: the same sheets hop by hop (``--anchor``), and the path given at import.

The sheets (``artifacts/pilot_gold_<id>.csv``) quote the corpus and stay gitignored. The
finder's recall is limited (spelling variants, OCR, references by one party's name); the
same gold is used for every system, so the limit does not favour one of them.
"""

import argparse
import csv
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, text

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.evaluation.retrieval import GoldPassage
from experiments.graphrag.extraction.case_names import significant_words
from experiments.graphrag.manifest import ARTIFACTS_DIR, RUNS_DIR
from experiments.graphrag.pilot.questions import PILOT_FILE, PilotQuestion, load_pilot, save_pilot

GHALII = "https://ghalii.org"
CONTEXT = 300
# A sheet is never silently truncated: rows are ordered by date, so a cap would drop the
# latest citing cases. Hitting it is reported, and the writer can narrow the search.
MAX_ROWS = 1000
# GoldPassage.text's own minimum: a shorter quote is reported, not a crash.
GOLD_TEXT_MIN = GoldPassage.model_fields["text"].metadata[0].min_length
# Party words too common to identify a case (shared with name resolution, but no resolver
# code runs here).
GENERIC = frozenset(
    "REPUBLIC STATE PEOPLE ATTORNEY GENERAL INSPECTOR POLICE COMMISSIONER GHANA GOVERNMENT "
    "HIGH COURT CIRCUIT DISTRICT TRIBUNAL CHIEF BANK COUNCIL ASSEMBLY AUTHORITY COMMISSION "
    "BOARD SERVICE UNITED FEDERAL".split()
)
_SIDE = re.compile(r"[\s\-–]+(?:versus|v\s?rs|vs|v)\.?[\s\-–]+", re.IGNORECASE)
SHEET_COLUMNS = (
    "row",
    "chunk_id",
    "judgment_uri",
    "citation",
    "date",
    "matched",
    "context",
    "ghalii_link",
    "cited_uri",
    "relevant",
    "on_issue",
    "gold_text",
    "note",
)


def citation_pattern(citation: str) -> str:
    """A Postgres regex for a citation with flexible spacing: "[2012] 1 SCGLR 391"."""
    tokens = re.findall(r"[A-Za-z]+|\d+", citation)
    return r"\s*[\[\(\]\)]?\s*".join(re.escape(t) for t in tokens) + r"\M"


def side_patterns(title: str) -> list[str]:
    """One regex per party side with identifying words; a lone side needs two words."""
    sides = [
        # Three letters, as everywhere in name matching: short surnames ("Adu", "Boi") count.
        sorted(w for w in significant_words(side.split()) if w not in GENERIC)
        for side in _SIDE.split(title)
    ]
    sides = [side for side in sides if side]
    if len(sides) >= 2:
        return [r"\m(" + "|".join(side) + r")\M" for side in sides[:2]]
    if sides and len(sides[0]) >= 2:
        return [rf"\m{word}\M" for word in sides[0][:2]]
    return []


def _anchor(conn: Connection, uri: str) -> Any:
    row = conn.execute(
        text(
            "SELECT j.id::text AS id, j.canonical_uri, coalesce(j.title, j.citation) AS title, "
            "j.neutral_citation, j.judgment_date, "
            "(SELECT min(source_text_hash) FROM chunks c WHERE c.judgment_id = j.id) AS grp "
            "FROM judgments j WHERE j.canonical_uri = :uri AND j.eligibility_status = 'eligible'"
        ),
        {"uri": uri},
    ).first()
    if row is None:
        raise ValueError(f"{uri} is not an eligible judgment")
    return row


def _context(content: str, pattern: str) -> tuple[str, str]:
    match = re.search(pattern.replace(r"\m", r"\b").replace(r"\M", r"\b"), content, re.IGNORECASE)
    if match is None:
        return "", " ".join(content[: 2 * CONTEXT].split())
    start = max(0, match.start() - CONTEXT)
    return match.group(0), " ".join(content[start : match.end() + CONTEXT].split())


def incoming_rows(
    conn: Connection, anchor: Any, extra_citations: list[str]
) -> list[dict[str, Any]]:
    names = side_patterns(anchor.title)
    citations = [c for c in [anchor.neutral_citation, *extra_citations] if c]
    conditions: list[str] = []
    params: dict[str, Any] = {"grp": anchor.grp, "limit": MAX_ROWS}
    if names:
        name_sql = " AND ".join(f"c.content ~* :name{i}" for i in range(len(names)))
        conditions.append(f"({name_sql})")
        params.update({f"name{i}": p for i, p in enumerate(names)})
    for i, citation in enumerate(citations):
        conditions.append(f"c.content ~* :cite{i}")
        params[f"cite{i}"] = citation_pattern(citation)
    if not conditions:
        return []
    rows = conn.execute(
        text(
            "SELECT c.id::text AS chunk_id, c.content, j.canonical_uri, j.citation, "
            "j.judgment_date FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            "WHERE j.eligibility_status = 'eligible' AND c.source_text_hash <> :grp "
            f"AND ({' OR '.join(conditions)}) "
            "ORDER BY j.judgment_date NULLS LAST, j.canonical_uri, c.ordinal LIMIT :limit"
        ),
        params,
    )
    patterns = [params[k] for k in sorted(params) if k.startswith(("cite", "name"))]
    out = []
    for row in rows:
        matched, context = "", ""
        for pattern in patterns:
            matched, context = _context(row.content, pattern)
            if matched:
                break
        out.append(
            {
                "chunk_id": row.chunk_id,
                "judgment_uri": row.canonical_uri,
                "citation": row.citation,
                "date": row.judgment_date.isoformat() if row.judgment_date else "",
                "matched": matched,
                "context": context,
                "ghalii_link": GHALII + row.canonical_uri,
            }
        )
    return out


_REFERENCE = re.compile(r"\S+\s+(?:v|vs|vrs|versus)\.?\s+\S+|[\[(]\s*(?:19|20)\d\d", re.IGNORECASE)


def outgoing_rows(conn: Connection, anchor: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT c.id::text AS chunk_id, c.content FROM chunks c "
            "WHERE c.judgment_id::text = :id ORDER BY c.ordinal"
        ),
        {"id": anchor.id},
    )
    out = []
    for row in rows:
        for match in _REFERENCE.finditer(row.content):
            start = max(0, match.start() - CONTEXT)
            out.append(
                {
                    "chunk_id": row.chunk_id,
                    "judgment_uri": anchor.canonical_uri,
                    "citation": "",
                    "date": "",
                    "matched": match.group(0),
                    "context": " ".join(row.content[start : match.end() + CONTEXT].split()),
                    "ghalii_link": GHALII + anchor.canonical_uri,
                }
            )
    return out[:MAX_ROWS]


def lookup(conn: Connection, citation: str | None, name: str | None) -> list[Any]:
    """Judgments by neutral citation or by both parties' words in the citation."""
    if citation:
        return list(
            conn.execute(
                text(
                    "SELECT canonical_uri, citation, judgment_date FROM judgments "
                    "WHERE eligibility_status = 'eligible' AND citation ~* :p LIMIT 20"
                ),
                {"p": citation_pattern(citation)},
            )
        )
    patterns = side_patterns(name or "")
    if not patterns:
        return []
    where = " AND ".join(f"coalesce(title, citation) ~* :p{i}" for i in range(len(patterns)))
    return list(
        conn.execute(
            text(
                "SELECT canonical_uri, citation, judgment_date FROM judgments "
                f"WHERE eligibility_status = 'eligible' AND {where} "
                "ORDER BY judgment_date LIMIT 20"
            ),
            {f"p{i}": p for i, p in enumerate(patterns)},
        )
    )


def _yes(value: str | None) -> bool:
    return (value or "").strip().lower() in {"y", "yes", "1", "true"}


def _validated(
    conn: Connection,
    rows: list[dict[str, str]],
    excluded: list[dict[str, str]] | None = None,
) -> tuple[list[tuple[dict[str, str], str]], list[GoldPassage], list[str]]:
    """Rows marked relevant *and* on issue: (row, gold case) pairs, their verbatim gold
    passages, and problems (an ineligible cited case, a gold text not in its chunk).

    With ``excluded`` (corpus-only gold), a cited case that is not an eligible corpus
    judgment is no problem: the row is left out with its passage and recorded there. No
    system can retrieve an authority the corpus does not hold."""
    problems: list[str] = []
    chosen = [r for r in rows if _yes(r.get("relevant")) and _yes(r.get("on_issue"))]
    chunk_ids = sorted({r["chunk_id"] for r in chosen})
    contents = {
        row.id: (row.content, row.canonical_uri)
        for row in conn.execute(
            text(
                "SELECT c.id::text AS id, c.content, j.canonical_uri FROM chunks c "
                "JOIN judgments j ON j.id = c.judgment_id WHERE c.id::text IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": chunk_ids or [""]},
        )
    }
    cases: list[tuple[dict[str, str], str]] = []
    passages: list[GoldPassage] = []
    for r in chosen:
        cited = (r.get("cited_uri") or "").strip()
        if cited:
            try:
                _anchor(conn, cited)
            except ValueError as exc:
                if excluded is None:
                    problems.append(f"row {r['row']}: {exc}")
                else:
                    excluded.append(r)
                continue
        cases.append((r, cited or r["judgment_uri"]))
        gold_text = " ".join((r.get("gold_text") or "").split())
        if gold_text:
            content, uri = contents.get(r["chunk_id"], ("", ""))
            if gold_text not in " ".join(content.split()):
                problems.append(
                    f"row {r['row']}: gold_text does not occur in chunk {r['chunk_id']}"
                )
            elif len(gold_text) < GOLD_TEXT_MIN:
                problems.append(
                    f"row {r['row']}: gold_text {gold_text!r} is shorter than "
                    f"{GOLD_TEXT_MIN} characters (too short to identify a passage)"
                )
            else:
                passages.append(GoldPassage(canonical_uri=uri, text=gold_text))
    return cases, passages, problems


def import_gold(
    conn: Connection,
    question: PilotQuestion,
    rows: list[dict[str, str]],
    excluded: list[dict[str, str]] | None = None,
) -> list[str]:
    """Adds the marked rows of an incoming or outgoing sheet as gold (corpus-only when
    ``excluded`` is given; see ``_validated``)."""
    cases, passages, problems = _validated(conn, rows, excluded)
    if problems:
        return problems
    question.gold_case_uris = sorted(set(question.gold_case_uris) | {case for _, case in cases})
    question.gold_passages = [*question.gold_passages, *passages]
    return []


def second_hop_rows(
    conn: Connection, question: PilotQuestion, first_hops: list[str], skipped: list[str]
) -> list[dict[str, Any]]:
    """The finder run from every first-hop case, in the question's direction, with the
    first hop each candidate continues from. A first hop that is not an eligible corpus
    judgment cannot be gold: it is skipped and reported in ``skipped``."""
    rows: list[dict[str, Any]] = []
    for hop in first_hops:
        try:
            anchor = _anchor(conn, hop)
        except ValueError:
            skipped.append(hop)
            continue
        found = (
            incoming_rows(conn, anchor, [])
            if question.traversal_direction() == "incoming"
            else outgoing_rows(conn, anchor)
        )
        rows += [{**row, "first_hop_uri": hop} for row in found]
    return rows


def import_lineage(
    conn: Connection,
    question: PilotQuestion,
    first_hops: list[str],
    first_rows: list[dict[str, str]],
    second_rows: list[dict[str, str]],
    excluded: list[dict[str, str]] | None = None,
) -> list[str]:
    """Complete chains (anchor, first hop, second hop) from the marked second-hop sheet;
    gold passages from both marked sheets. A chain's first hop must be an accepted one."""
    _, first_passages, problems = _validated(conn, first_rows, excluded)
    second, second_passages, more = _validated(conn, second_rows, excluded)
    problems += more
    anchor = question.anchor_uris[0]
    chains: list[list[str]] = []
    for row, case in second:
        hop = (row.get("first_hop_uri") or "").strip()
        if hop not in first_hops:
            problems.append(f"row {row['row']}: first hop {hop or '(none)'} was not accepted")
            continue
        try:
            _anchor(conn, hop)
        except ValueError as exc:
            problems.append(f"row {row['row']}: first hop: {exc}")
            continue
        if case in (anchor, hop):
            problems.append(f"row {row['row']}: a chain does not revisit {case}")
            continue
        chains.append([anchor, hop, case])
    if not chains:
        problems.append("no complete chain was marked")
    if problems:
        return problems
    question.gold_paths = [list(c) for c in sorted({tuple(c) for c in chains})]
    question.gold_case_uris = sorted({case for chain in question.gold_paths for case in chain[1:]})
    # A first hop that no marked chain continues is not gold, so neither is its passage.
    on_chain = {case for chain in question.gold_paths for case in chain}
    question.gold_passages = [
        p for p in [*first_passages, *second_passages] if p.canonical_uri in on_chain
    ]
    return []


OUTSIDE_CORPUS_COLUMNS = ("question_id", "sheet_row", "cited_uri", "recorded_at")


def record_outside_corpus(question_id: str, rows: list[dict[str, str]], out_dir: Path) -> None:
    """Appends authorities a reviewer accepted that the corpus does not hold to
    ``runs/pilot_outside_corpus.csv``: identifiers only, no corpus text (committable)."""
    path = out_dir / "pilot_outside_corpus.csv"
    known: set[tuple[str, str]] = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            known = {(r["question_id"], r["cited_uri"]) for r in csv.DictReader(handle)}
    new = [r for r in rows if (question_id, r["cited_uri"].strip()) not in known]
    if not new:
        return
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTSIDE_CORPUS_COLUMNS))
        if write_header:
            writer.writeheader()
        for r in new:
            writer.writerow(
                {
                    "question_id": question_id,
                    "sheet_row": r["row"],
                    "cited_uri": r["cited_uri"].strip(),
                    "recorded_at": f"{datetime.now(UTC):%Y-%m-%d}",
                }
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.pilot.gold_finder")
    parser.add_argument("--file", type=Path, default=PILOT_FILE)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=RUNS_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    sheet = commands.add_parser("sheet")
    sheet.add_argument("--question", required=True)
    sheet.add_argument("--anchor", help="another hop of a lineage question")
    sheet.add_argument("--direction", choices=("incoming", "outgoing"))
    found = commands.add_parser("lookup")
    found.add_argument("--citation")
    found.add_argument("--name")
    imported = commands.add_parser("import", help="an incoming or outgoing question's sheet")
    imported.add_argument("--question", required=True)
    imported.add_argument("--sheet", type=Path, required=True)
    imported.add_argument(
        "--corpus-only",
        action="store_true",
        help="leave out cited cases the corpus does not hold, and record them",
    )
    hop2 = commands.add_parser("hop2", help="a lineage question's second-hop sheet")
    hop2.add_argument("--question", required=True)
    hop2.add_argument("--first-hops", type=Path, required=True)
    lineage = commands.add_parser("import-lineage", help="a lineage question's chains")
    lineage.add_argument("--question", required=True)
    lineage.add_argument("--first-hops", type=Path, required=True)
    lineage.add_argument("--first-sheet", type=Path, required=True)
    lineage.add_argument("--second-sheet", type=Path, required=True)
    lineage.add_argument("--corpus-only", action="store_true")
    args = parser.parse_args(argv)

    def read(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def first_hops_of(question_id: str) -> list[str]:
        rows = read(args.first_hops)
        return sorted({r["first_hop_uri"].strip() for r in rows if r["question_id"] == question_id})

    questions = {q.id: q for q in load_pilot(args.file)}
    engine = make_engine(get_settings())
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if args.command == "lookup":
                for row in lookup(conn, args.citation, args.name):
                    sys.stdout.write(f"{row.canonical_uri}\t{row.judgment_date}\t{row.citation}\n")
                return 0
            question = questions.get(args.question)
            if question is None:
                sys.stderr.write(f"no question {args.question} in {args.file}\n")
                return 1
            if (
                question.intent_locked_at is None
                or question.intent_hash != question.intent_digest()
            ):
                sys.stderr.write("lock the intent first (questions lock-intents)\n")
                return 1
            if question.gold_locked_at is not None:
                sys.stderr.write("the gold of this question is already locked\n")
                return 1
            if args.command == "hop2":
                if question.question_class != "lineage":
                    sys.stderr.write("second-hop sheets are for lineage questions\n")
                    return 1
                skipped: list[str] = []
                rows = second_hop_rows(conn, question, first_hops_of(question.id), skipped)
                for hop in skipped:
                    sys.stderr.write(f"skipped first hop {hop}: not an eligible corpus judgment\n")
                out = args.artifacts / f"pilot_gold_{question.id}_hop2.csv"
                with out.open("w", newline="", encoding="utf-8") as handle:
                    columns = [*SHEET_COLUMNS, "first_hop_uri"]
                    writer = csv.DictWriter(handle, fieldnames=columns)
                    writer.writeheader()
                    for number, row in enumerate(rows, start=1):
                        writer.writerow({**{c: "" for c in columns}, **row, "row": number})
                sys.stdout.write(f"wrote {len(rows)} second-hop candidate rows to {out}\n")
                return 0
            if args.command == "import-lineage":
                left_out: list[dict[str, str]] | None = [] if args.corpus_only else None
                problems = import_lineage(
                    conn,
                    question,
                    first_hops_of(question.id),
                    read(args.first_sheet),
                    read(args.second_sheet),
                    left_out,
                )
                if left_out:
                    record_outside_corpus(question.id, left_out, args.out_dir)
            if args.command == "sheet":
                anchor = _anchor(conn, args.anchor or question.anchor_uris[0])
                direction = args.direction or question.traversal_direction()
                rows = (
                    incoming_rows(conn, anchor, question.anchor_citations)
                    if direction == "incoming"
                    else outgoing_rows(conn, anchor)
                )
                out = (
                    args.artifacts / f"pilot_gold_{question.id}{'_hop' if args.anchor else ''}.csv"
                )
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(SHEET_COLUMNS))
                    writer.writeheader()
                    for number, row in enumerate(rows, start=1):
                        writer.writerow({**{c: "" for c in SHEET_COLUMNS}, **row, "row": number})
                capped = " (CAP REACHED: some candidates are missing; narrow the search)"
                sys.stdout.write(
                    f"wrote {len(rows)} candidate rows to {out}"
                    f"{capped if len(rows) >= MAX_ROWS else ''}\n"
                )
                return 0
            if args.command == "import":
                excluded: list[dict[str, str]] | None = [] if args.corpus_only else None
                problems = import_gold(conn, question, read(args.sheet), excluded)
                if excluded:
                    record_outside_corpus(question.id, excluded, args.out_dir)
    finally:
        engine.dispose()
    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        return 1
    save_pilot(list(questions.values()), args.file)
    sys.stdout.write(
        f"{question.id}: {len(question.gold_case_uris)} gold cases, "
        f"{len(question.gold_passages)} gold passages (at {datetime.now(UTC):%Y-%m-%d %H:%M})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
