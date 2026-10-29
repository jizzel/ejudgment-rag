"""Phase 3 pilot questions: format, validation and the two locks.

    python -m experiments.graphrag.pilot.questions import-intents --sheet intents.csv
    python -m experiments.graphrag.pilot.questions draw-locals [--n 8] [--seed 20261029]
    python -m experiments.graphrag.pilot.questions lock-intents
    python -m experiments.graphrag.pilot.questions lock-gold
    python -m experiments.graphrag.pilot.questions retire|stress-test --id <id> --reason "…"

The question set is written **before any system runs** (docs/graphrag/AGENTS.md rule 6):

1. The writer (Lexi) writes relational intents blind, from the seed sheet; local controls
   are drawn from the existing gold set by a seeded sample.
2. ``lock-intents`` freezes each question's wording, class, anchors, direction and filters
   (``intent_hash``). Gold finding comes after, and never edits a locked intent.
3. Verified gold is imported (``gold_finder import``); ``lock-gold`` freezes it
   (``gold_hash``). The runner refuses a set with an unlocked or changed question.

Classes: ``local`` (one-judgment questions, controls), ``outgoing`` (what a case relied on:
follow ``CITES``), ``incoming`` (how a case was treated later: follow ``CITED_BY``) and
``lineage`` (a two-hop chain, direction given per question).
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ejudgment.domain.schemas import SearchFilters
from ejudgment.evaluation.retrieval import GoldPassage, load_gold

PILOT_FILE = Path("evals/graphrag_pilot.jsonl")
PilotClass = Literal["local", "outgoing", "incoming", "lineage"]
Direction = Literal["outgoing", "incoming"]
CLASS_DIRECTION: dict[str, Direction | None] = {
    "local": None,
    "outgoing": "outgoing",
    "incoming": "incoming",
}


class PilotQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    question_class: PilotClass
    query: str = Field(min_length=1, max_length=1000)
    intent: str = ""
    anchor_uris: list[str] = Field(default_factory=list)
    # Report citations of the anchor the writer knows ("[2012] 1 SCGLR 391"): extra search
    # terms for the gold finder, never shown to a system.
    anchor_citations: list[str] = Field(default_factory=list)
    direction: Direction | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    gold_case_uris: list[str] = Field(default_factory=list)
    gold_passages: list[GoldPassage] = Field(default_factory=list)
    # Lineage: every complete chain the gold review established, each ordered from the
    # anchor (anchor, first hop, second hop). One question can have many chains.
    gold_paths: list[list[str]] = Field(default_factory=list)
    sampling: str = ""
    written_by: str = ""
    provisional: bool = False  # local controls drawn from the unreviewed gold set
    intent_locked_at: datetime | None = None
    intent_hash: str | None = None
    gold_locked_at: datetime | None = None
    gold_hash: str | None = None
    # A retired question stays in the file, with its locked intent and the reason, but is
    # neither gold-locked nor run (e.g. the corpus holds no answer to score against).
    retired: bool = False
    retired_reason: str = ""
    # A stress test is run and reported separately, never in the primary scores: e.g. a
    # lineage question whose gold universe is far larger than the others' (capping it after
    # the wording was locked would bias it). Its gold may stop at the first hop.
    stress_test: bool = False
    stress_test_reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _single_path(cls, data: object) -> object:
        """Earlier records held one ``gold_path``; read it as a list of one chain."""
        if isinstance(data, dict) and "gold_path" in data:
            data = dict(data)
            path = data.pop("gold_path")
            if path and not data.get("gold_paths"):
                data["gold_paths"] = [path]
        return data

    def traversal_direction(self) -> Direction | None:
        """The labelled direction: the class's own, or the question's for lineage."""
        return CLASS_DIRECTION.get(self.question_class, self.direction)

    def intent_digest(self) -> str:
        frozen = {
            "id": self.id,
            "class": self.question_class,
            "query": self.query,
            "anchors": sorted(self.anchor_uris),
            "direction": self.traversal_direction(),
            "filters": self.filters.model_dump(mode="json"),
        }
        return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()

    def gold_digest(self) -> str:
        frozen = {
            "cases": sorted(self.gold_case_uris),
            "passages": sorted((p.canonical_uri, p.text) for p in self.gold_passages),
            "paths": sorted(self.gold_paths),
            # Frozen with the gold, so a question cannot leave the primary set after a run.
            "stress_test": self.stress_test,
        }
        return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()


def intent_problems(question: PilotQuestion) -> list[str]:
    problems: list[str] = []
    relational = question.question_class != "local"
    if relational and not question.anchor_uris:
        problems.append("a relational question names its anchor case(s)")
    if question.question_class == "lineage" and question.direction is None:
        problems.append("a lineage question states its direction")
    if question.question_class in CLASS_DIRECTION and question.direction not in (
        None,
        CLASS_DIRECTION[question.question_class],
    ):
        problems.append("direction contradicts the class")
    if relational and not question.sampling:
        problems.append("record how the anchor was chosen (sampling)")
    return problems


def gold_problems(question: PilotQuestion) -> list[str]:
    problems: list[str] = []
    gold = set(question.gold_case_uris)
    if not gold:
        problems.append("no gold cases")
    # A supporting passage lies in a gold case, or (outgoing, lineage) in the anchor that
    # cites one: "what did X rely on" is answered by X's own citing passage.
    allowed = gold | set(question.anchor_uris)
    for passage in question.gold_passages:
        if passage.canonical_uri not in allowed:
            problems.append(
                f"gold passage of {passage.canonical_uri} is not in a gold or anchor case"
            )
    if question.question_class == "lineage":
        if not question.gold_paths and not question.stress_test:
            problems.append("a lineage question has at least one complete chain")
        for path in question.gold_paths:
            if len(path) < 3:
                problems.append(f"chain {path}: a lineage chain has at least three cases")
            elif path[0] not in question.anchor_uris:
                problems.append(f"chain {path}: it does not start at the anchor")
            elif not set(path[1:]) <= gold:
                problems.append(f"chain {path}: every case after the anchor is a gold case")
    return problems


def load_pilot(path: Path = PILOT_FILE) -> list[PilotQuestion]:
    if not path.exists():
        return []
    questions = [
        PilotQuestion.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids")
    return questions


def save_pilot(questions: list[PilotQuestion], path: Path = PILOT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        q.model_dump_json(exclude_none=False) + "\n" for q in sorted(questions, key=lambda q: q.id)
    )
    path.write_text(body, encoding="utf-8")


def run_problems(questions: list[PilotQuestion]) -> list[str]:
    """Why a question set may not be run: every intent and gold locked and unchanged."""
    problems: list[str] = []
    active = [q for q in questions if not q.retired]
    if not active:
        return ["no questions"]
    for q in active:
        if q.intent_locked_at is None or q.intent_hash != q.intent_digest():
            problems.append(f"{q.id}: intent not locked, or changed since it was locked")
        if q.gold_locked_at is None or q.gold_hash != q.gold_digest():
            problems.append(f"{q.id}: gold not locked, or changed since it was locked")
    return problems


def lock_intents(questions: list[PilotQuestion], now: datetime) -> list[str]:
    """Stamps unlocked intents; refuses (and changes nothing) if any intent is incomplete
    or a locked one was edited."""
    problems = [f"{q.id}: {p}" for q in questions for p in intent_problems(q)]
    problems += [
        f"{q.id}: intent changed after it was locked"
        for q in questions
        if q.intent_locked_at is not None and q.intent_hash != q.intent_digest()
    ]
    if problems:
        return problems
    for q in questions:
        if q.intent_locked_at is None:
            q.intent_locked_at, q.intent_hash = now, q.intent_digest()
    return []


def lock_gold(questions: list[PilotQuestion], now: datetime) -> list[str]:
    active = [q for q in questions if not q.retired]
    problems = [
        f"{q.id}: intent not locked"
        for q in active
        if q.intent_locked_at is None or q.intent_hash != q.intent_digest()
    ]
    problems += [f"{q.id}: {p}" for q in active for p in gold_problems(q)]
    # A lock is never re-stamped: gold edited after locking (say, after seeing a run) is
    # refused, as an edited intent is.
    problems += [
        f"{q.id}: gold changed after it was locked"
        for q in active
        if q.gold_locked_at is not None and q.gold_hash != q.gold_digest()
    ]
    if problems:
        return problems
    for q in active:
        if q.gold_locked_at is None:
            q.gold_locked_at, q.gold_hash = now, q.gold_digest()
    return []


def retire(questions: list[PilotQuestion], question_id: str, reason: str) -> list[str]:
    """Retires a question that cannot be scored; its locked intent is kept unchanged."""
    match = [q for q in questions if q.id == question_id]
    if not match:
        return [f"no question {question_id}"]
    if not reason.strip():
        return ["give the reason for retiring it"]
    if match[0].gold_locked_at is not None:
        return [f"{question_id}: its gold is already locked"]
    match[0].retired, match[0].retired_reason = True, reason.strip()
    return []


def mark_stress_test(questions: list[PilotQuestion], question_id: str, reason: str) -> list[str]:
    """Moves a question out of the primary scores into the separately reported stress tests."""
    match = [q for q in questions if q.id == question_id]
    if not match:
        return [f"no question {question_id}"]
    if not reason.strip():
        return ["give the reason for the stress test"]
    if match[0].gold_locked_at is not None:
        return [f"{question_id}: its gold is already locked"]
    match[0].stress_test, match[0].stress_test_reason = True, reason.strip()
    return []


def import_intents(sheet: Path) -> list[PilotQuestion]:
    """The writer's sheet: id, class, query, intent, anchor_uris, anchor_citations,
    direction, sampling, written_by (lists separated by ';')."""

    def items(value: str | None) -> list[str]:
        return [v.strip() for v in (value or "").split(";") if v.strip()]

    with sheet.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        PilotQuestion.model_validate(
            {
                "id": row["id"].strip(),
                "question_class": row["class"].strip(),
                "query": row["query"].strip(),
                "intent": (row.get("intent") or "").strip(),
                "anchor_uris": items(row.get("anchor_uris")),
                "anchor_citations": items(row.get("anchor_citations")),
                "direction": (row.get("direction") or "").strip() or None,
                "sampling": (row.get("sampling") or "").strip(),
                "written_by": (row.get("written_by") or "").strip(),
            }
        )
        for row in rows
        if (row.get("id") or "").strip()
    ]


def draw_locals(gold_path: Path, n: int, seed: int) -> list[PilotQuestion]:
    """Seeded sample of answerable issue and fact-pattern questions from the gold set."""
    pool = [
        q
        for q in load_gold(gold_path)
        if q.category in ("issue", "fact_pattern")
        and q.gold_canonical_uris
        and not q.expect_no_answer
    ]
    rng = random.Random(seed)
    chosen = rng.sample(sorted(pool, key=lambda q: q.id), min(n, len(pool)))
    return [
        PilotQuestion(
            id=f"local-{q.id}",
            question_class="local",
            query=q.question,
            intent=f"control: {q.category} question {q.id} from {gold_path}",
            filters=q.filters,
            gold_case_uris=list(q.gold_canonical_uris),
            gold_passages=list(q.gold_passages),
            sampling=f"seeded draw (seed {seed}) from {gold_path} issue/fact_pattern questions",
            written_by="evals/gold.jsonl (engineer-drafted)",
            provisional=not q.reviewed,
        )
        for q in sorted(chosen, key=lambda q: q.id)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.pilot.questions")
    parser.add_argument("--file", type=Path, default=PILOT_FILE)
    commands = parser.add_subparsers(dest="command", required=True)
    imported = commands.add_parser("import-intents")
    imported.add_argument("--sheet", type=Path, required=True)
    drawn = commands.add_parser("draw-locals")
    drawn.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    drawn.add_argument("--n", type=int, default=8)
    drawn.add_argument("--seed", type=int, default=20261029)
    retired = commands.add_parser("retire")
    retired.add_argument("--id", required=True)
    retired.add_argument("--reason", required=True)
    stress = commands.add_parser("stress-test", help="report a question apart from the pilot")
    stress.add_argument("--id", required=True)
    stress.add_argument("--reason", required=True)
    commands.add_parser("lock-intents")
    commands.add_parser("lock-gold")
    commands.add_parser("check")
    args = parser.parse_args(argv)

    questions = load_pilot(args.file)
    existing = {q.id for q in questions}
    now = datetime.now(UTC)
    if args.command in ("import-intents", "draw-locals"):
        new = (
            import_intents(args.sheet)
            if args.command == "import-intents"
            else draw_locals(args.gold, args.n, args.seed)
        )
        clash = sorted(q.id for q in new if q.id in existing)
        if clash:
            sys.stderr.write(f"already in {args.file} (never overwritten): {', '.join(clash)}\n")
            return 1
        save_pilot(questions + new, args.file)
        sys.stdout.write(f"added {len(new)} questions to {args.file}\n")
        return 0
    if args.command in ("retire", "stress-test"):
        marker = retire if args.command == "retire" else mark_stress_test
        problems = marker(questions, args.id, args.reason)
        if not problems:
            save_pilot(questions, args.file)
    elif args.command == "check":
        problems = run_problems(questions)
    else:
        locker = lock_intents if args.command == "lock-intents" else lock_gold
        problems = locker(questions, now)
        if not problems:
            save_pilot(questions, args.file)
    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        return 1
    sys.stdout.write(f"{args.command}: {len(questions)} questions ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
