"""Search from the command line (prints the API's JSON shape, for inspecting failures).

python -m ejudgment.worker.search "landlord eviction" --court ghasc --year-from 2015
"""

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.domain.schemas import SearchFilters, SearchRequest
from ejudgment.retrieval.service import search


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ejudgment.worker.search", description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--court")
    parser.add_argument("--jurisdiction")
    parser.add_argument("--year-from", type=int)
    parser.add_argument("--year-to", type=int)
    parser.add_argument("--judge")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        request = SearchRequest(
            query=args.query,
            top_k=args.top_k,
            filters=SearchFilters(
                court=args.court,
                jurisdiction=args.jurisdiction,
                year_from=args.year_from,
                year_to=args.year_to,
                judge=args.judge,
            ),
        )
    except ValidationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    settings = get_settings()
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            response = search(conn, request, settings)
    finally:
        engine.dispose()
    sys.stdout.write(response.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
