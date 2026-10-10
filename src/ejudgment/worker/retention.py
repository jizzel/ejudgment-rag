"""Apply the data-retention policy (run daily, e.g. from cron).

python -m ejudgment.worker.retention
"""

import argparse
import json
import sys
from collections.abc import Sequence

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.retention import apply_retention


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(prog="ejudgment.worker.retention", description=__doc__).parse_args(argv)
    settings = get_settings()
    engine = make_engine(settings)
    try:
        deleted = apply_retention(engine, settings)
    finally:
        engine.dispose()
    json.dump({"deleted": deleted}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
