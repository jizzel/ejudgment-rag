"""Benchmark our search against GhaLII's site search (docs/benchmark-ghalii.md).

1. for the query writer (questions only, no gold cases):
   python -m ejudgment.worker.benchmark_ghalii queries --out queries.csv
2. for the recorder (both queries, facets to set, cases to look for):
   python -m ejudgment.worker.benchmark_ghalii sheet --queries queries.csv --out sheet.csv
3. check the filled sheet, run our search on the same queries, store an evaluation run:
   python -m ejudgment.worker.benchmark_ghalii score --sheet sheet.csv

GhaLII is searched by hand in a browser; nothing here contacts it.
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.domain.schemas import SearchRequest
from ejudgment.embeddings.loading import load_providers
from ejudgment.evaluation import ghalii_benchmark as bench
from ejudgment.evaluation.retrieval import RECALL_AT, load_gold, run_config, store_run
from ejudgment.ingestion.hashing import sha256_file
from ejudgment.retrieval import repository
from ejudgment.retrieval.service import search


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ejudgment.worker.benchmark_ghalii", description=__doc__)
    parser.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    commands = parser.add_subparsers(dest="command", required=True)
    queries = commands.add_parser("queries", help="write the sheet for the keyword-query writer")
    queries.add_argument("--out", type=Path, required=True)
    sheet = commands.add_parser("sheet", help="write the recording sheet")
    sheet.add_argument("--queries", type=Path, required=True)
    sheet.add_argument("--out", type=Path, required=True)
    score = commands.add_parser("score", help="check and score a filled recording sheet")
    score.add_argument("--sheet", type=Path, required=True)
    args = parser.parse_args(argv)

    questions = load_gold(args.gold)
    if args.command == "queries":
        bench.write_query_sheet(questions, args.out)
        sys.stdout.write(f"wrote {args.out} ({len(questions)} questions)\n")
        return 0

    settings = get_settings()
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            gold_uris = sorted({u for q in questions for u in q.gold_canonical_uris})
            copies = bench.case_copies(conn, gold_uris)
            if args.command == "sheet":
                try:
                    keyword_queries = bench.read_keyword_queries(args.queries, questions)
                except ValueError as exc:
                    sys.stderr.write(f"{args.queries}: {exc}\n")
                    return 1
                names = {code: name or code for code, name, _ in repository.courts(conn)}
                bench.write_recording_sheet(questions, keyword_queries, copies, names, args.out)
                sys.stdout.write(f"wrote {args.out} ({len(questions)} questions)\n")
                return 0
            try:
                recorded = bench.read_recording_sheet(args.sheet, questions, copies)
            except ValueError as exc:
                sys.stderr.write(f"{args.sheet}: the sheet is not complete:\n{exc}\n")
                return 1
            embedder, reranker = load_providers(settings)
            by_id = {q.id: q for q in questions}
            records: list[dict[str, Any]] = []
            for row in recorded:
                question = by_id[row.question_id]
                # Our default search (hybrid + rerank) on the very same query string and filters.
                response = search(
                    conn,
                    SearchRequest(query=row.query, filters=question.filters, top_k=RECALL_AT),
                    settings,
                    embedder=embedder,
                    reranker=reranker,
                )
                gold_copies = [c for u in question.gold_canonical_uris for c in copies.get(u, [])]
                records.append(
                    {
                        "id": question.id,
                        "arm": row.arm,
                        "query": row.query,
                        "category": question.category,
                        "reviewed": question.reviewed,
                        "expect_no_answer": question.expect_no_answer,
                        "ghalii_rank": row.rank,
                        "ghalii_url": row.url,
                        "ghalii_result_count": row.result_count,
                        "searched_on": row.searched_on,
                        "ours_rank": bench.our_rank(response, gold_copies),
                        "ours_degraded": response.query_info.degraded,
                    }
                )
        metrics = bench.summarise(records)
        reviewed = [r for r in records if r["reviewed"]]
        metrics["reviewed"] = bench.summarise(reviewed) if reviewed else None
        config = run_config(engine, settings, args.gold, questions, embedder, reranker)
        config["kind"] = "ghalii_benchmark"
        config["sheet"] = str(args.sheet)
        config["sheet_sha256"] = sha256_file(args.sheet)
        config["searched_on"] = sorted({r["searched_on"] for r in records if r["searched_on"]})
        run_id = store_run(engine, config, metrics, records)
    finally:
        engine.dispose()
    label = "PROVISIONAL (unreviewed questions)" if config["provisional"] else "reviewed"
    sys.stdout.write(f"GhaLII benchmark run {run_id} - {label}\n")
    json.dump(metrics, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
