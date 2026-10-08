"""Offline ingestion CLI.

    python -m ejudgment.worker.ingest legacy \\
        --source output/pdf/judgments_with_text.db --pdf-base-dir . [--dry-run] [--limit N]

Paths are always explicit; nothing is picked by "latest mtime". No network access.
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.ingestion.legacy_adapter import LegacyExportError
from ejudgment.ingestion.service import run_legacy_import


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ejudgment.worker.ingest", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    legacy = commands.add_parser("legacy", help="Import the legacy SQLite export (read-only).")
    legacy.add_argument("--source", type=Path, required=True, help="Path to the export .db file")
    legacy.add_argument(
        "--pdf-base-dir",
        type=Path,
        required=True,
        help="Directory that the export's relative pdf_local_path values are resolved against",
    )
    legacy.add_argument(
        "--dry-run", action="store_true", help="Normalize and verify only; write nothing"
    )
    legacy.add_argument("--limit", type=int, default=None, help="Only process the first N rows")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.command == "legacy":
        engine = None if args.dry_run else make_engine(settings)
        try:
            report = run_legacy_import(
                args.source,
                args.pdf_base_dir,
                settings,
                engine=engine,
                dry_run=args.dry_run,
                limit=args.limit,
            )
        except LegacyExportError as exc:
            logging.error("%s", exc)
            return 2
        finally:
            if engine is not None:
                engine.dispose()
        json.dump(report.as_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
