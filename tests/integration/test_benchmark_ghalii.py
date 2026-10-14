import csv
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from ejudgment.config import Settings
from ejudgment.evaluation import ghalii_benchmark as bench
from ejudgment.evaluation.retrieval import GoldQuestion
from ejudgment.worker import benchmark_ghalii
from tests.fixtures import legacy_fixture as fx

pytestmark = pytest.mark.integration

TWIN_A = f"/akn/gh/judgment/ghasc/2020/{fx.ROW_TEXT_TWIN_A + 1}/eng@2020-01-19"


def test_a_degraded_search_is_not_scored(
    chat_engine: Engine,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without models our search falls back to keywords: scoring stops and stores nothing,
    rather than presenting a weakened search as the default."""
    question = GoldQuestion(
        id="q-a", question="marker text", category="issue", gold_canonical_uris=[TWIN_A]
    )
    gold = tmp_path / "gold.jsonl"
    gold.write_text(question.model_dump_json() + "\n")
    sheet = tmp_path / "sheet.csv"
    with chat_engine.connect() as conn:
        copies = bench.case_copies(conn, [TWIN_A])
    bench.write_recording_sheet([question], {"q-a": "marker"}, copies, {}, sheet)
    with sheet.open(newline="") as handle:
        (row,) = list(csv.DictReader(handle))
    row.update(
        verbatim_rank="none",
        keywords_rank="1",
        keywords_url=f"https://ghalii.org{TWIN_A}",
        searched_on=date.today().isoformat(),
    )
    with sheet.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=bench.SHEET_COLUMNS)
        writer.writeheader()
        writer.writerow(row)

    url = chat_engine.url.render_as_string(hide_password=False)
    monkeypatch.setattr(
        benchmark_ghalii, "get_settings", lambda: settings.model_copy(update={"database_url": url})
    )
    monkeypatch.setattr(benchmark_ghalii, "load_providers", lambda _settings: (None, None))

    assert benchmark_ghalii.main(["--gold", str(gold), "score", "--sheet", str(sheet)]) == 1
    err = capsys.readouterr().err
    assert "not scored" in err
    assert "q-a verbatim: embedding model unavailable; used lexical retrieval" in err
    with chat_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM evaluation_runs")).scalar() == 0
