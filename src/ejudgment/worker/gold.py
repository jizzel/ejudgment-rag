"""Gold set: move questions between evals/gold.jsonl and the review database; show progress.

python -m ejudgment.worker.gold import [--file evals/gold.jsonl]   # adds new ids (idempotent)
python -m ejudgment.worker.gold export [--file evals/gold.jsonl]   # non-retired; refuses incomplete
python -m ejudgment.worker.gold stats
Lawyers review in the app (/review); export afterwards so evaluations use the reviewed set.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.evaluation import gold_review
from ejudgment.evaluation.retrieval import load_gold


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ejudgment.worker.gold", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "export"):
        commands.add_parser(name).add_argument(
            "--file", type=Path, default=Path("evals/gold.jsonl")
        )
    commands.add_parser("stats")
    args = parser.parse_args(argv)

    engine = make_engine(get_settings())
    try:
        if args.command == "import":
            questions = load_gold(args.file)  # validated before anything is written
            with engine.begin() as conn:
                report = gold_review.import_questions(conn, questions)
            sys.stdout.write(
                f"imported {report.created}, unchanged {report.unchanged}, "
                f"different in the database (not overwritten): {report.differs or 'none'}\n"
            )
        elif args.command == "export":
            try:
                with engine.connect() as conn:
                    count = gold_review.export_jsonl(conn, args.file)
            except gold_review.GoldExportError as error:
                sys.stderr.write(f"not exported, {args.file} left unchanged: {error}\n")
                return 1
            sys.stdout.write(f"exported {count} questions to {args.file}\n")
        else:
            with engine.connect() as conn:
                json.dump(gold_review.counts(conn), sys.stdout, indent=2)
            sys.stdout.write("\n")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
