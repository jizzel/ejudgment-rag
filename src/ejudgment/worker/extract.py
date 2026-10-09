"""Convert Word files and OCR scanned PDFs that the import left without text.

    python -m ejudgment.worker.extract --pdf-base-dir . [--limit N]

Needs Tesseract and poppler on PATH (macOS: brew install tesseract poppler).
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.ingestion.extract_service import run_extraction
from ejudgment.ingestion.ocr import OcrError, TesseractOcr


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="ejudgment.worker.extract", description=__doc__)
    parser.add_argument(
        "--pdf-base-dir",
        type=Path,
        required=True,
        help="Directory the export's relative pdf_local_path values are resolved against",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only the first N judgments")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        ocr = TesseractOcr(settings)
    except OcrError as exc:
        logging.error("%s", exc)
        return 2
    engine = make_engine(settings)
    try:
        report = run_extraction(engine, settings, args.pdf_base_dir, ocr, limit=args.limit)
    finally:
        engine.dispose()
    json.dump(report.as_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
