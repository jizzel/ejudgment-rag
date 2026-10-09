"""Write the API's OpenAPI schema for the UI's generated TypeScript types.

python -m ejudgment.api.export_openapi [--out ui/src/lib/openapi.json]
Then: npm --prefix ui run gen:api. A test fails when the committed snapshot is stale.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ejudgment.api.main import create_app
from ejudgment.config import REPO_ROOT, Settings

DEFAULT_OUT = REPO_ROOT / "ui" / "src" / "lib" / "openapi.json"


def openapi_schema() -> dict[str, Any]:
    # Building the schema touches no database or model.
    schema: dict[str, Any] = create_app(Settings(), load_models=False).openapi()
    return schema


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ejudgment.api.export_openapi", description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(openapi_schema()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
