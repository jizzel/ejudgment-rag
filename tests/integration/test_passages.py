from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from ejudgment.api.main import create_app
from ejudgment.config import Settings
from ejudgment.domain.schemas import ATTRIBUTION, NOTICE
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from tests.fixtures import legacy_fixture as fx

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine) -> Engine:
    # Small chunks so each judgment has several passages to read in context.
    small = settings.model_copy(update={"chunk_target_tokens": 20, "chunk_max_tokens": 30})
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, small, engine=migrated_engine
    )
    run_chunking(migrated_engine, WhitespaceTokenizer(), small)
    return migrated_engine


@pytest.fixture
def client(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine, load_models=False)) as test_client:
        yield test_client


def _chunks(engine: Engine, title: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT c.id, c.ordinal FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
                    "WHERE j.title = :t ORDER BY c.ordinal"
                ),
                {"t": title},
            )
        )


def test_passage_with_its_neighbours(client: TestClient, engine: Engine) -> None:
    chunks = _chunks(engine, "Party37 Vrs Other37")
    assert len(chunks) >= 4
    middle = chunks[2]
    body = client.get(f"/v1/passages/{middle.id}", params={"context": 1}).json()
    assert body["passage"]["chunk_id"] == str(middle.id)
    assert [p["ordinal"] for p in body["before"]] == [1]
    assert [p["ordinal"] for p in body["after"]] == [3]
    assert body["judgment"]["citation"].startswith("Party37 Vrs Other37")
    assert body["judgment"]["source_url"].startswith("https://ghalii.org/akn/gh/judgment/ghasc/")
    assert (body["attribution"], body["notice"]) == (ATTRIBUTION, NOTICE)
    assert body["passage"]["page_reference_status"] == "unknown"
    assert body["passage"]["page_start"] is None  # legacy text: never a page

    first = client.get(f"/v1/passages/{chunks[0].id}", params={"context": 3}).json()
    assert first["before"] == [] and [p["ordinal"] for p in first["after"]] == [1, 2, 3]
    alone = client.get(f"/v1/passages/{middle.id}", params={"context": 0}).json()
    assert alone["before"] == alone["after"] == []


def test_verified_pages_are_shown(client: TestClient, engine: Engine) -> None:
    title = f"Party{fx.ROW_READABLE_PDF_NO_TEXT} Vrs Other{fx.ROW_READABLE_PDF_NO_TEXT}"
    chunk = _chunks(engine, title)[0]
    passage = client.get(f"/v1/passages/{chunk.id}").json()["passage"]
    assert passage["page_reference_status"] == "verified"
    assert passage["page_start"] is not None


def test_ineligible_or_unknown_passages_are_not_found(client: TestClient, engine: Engine) -> None:
    chunk = _chunks(engine, "Party37 Vrs Other37")[0]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE judgments SET eligibility_status = 'quarantined' WHERE title = :t"),
            {"t": "Party37 Vrs Other37"},
        )
    response = client.get(f"/v1/passages/{chunk.id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "passage_not_found"
    missing = client.get("/v1/passages/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert client.get(f"/v1/passages/{chunk.id}", params={"context": 9}).status_code == 422


def test_courts(client: TestClient, engine: Engine) -> None:
    courts = client.get("/v1/courts").json()["courts"]
    with engine.connect() as conn:
        expected = {
            row.court_code: row.n
            for row in conn.execute(
                text(
                    "SELECT court_code, count(*) AS n FROM judgments "
                    "WHERE eligibility_status = 'eligible' GROUP BY court_code"
                )
            )
        }
    assert {court["court_code"]: court["judgments"] for court in courts} == expected
    counts = [court["judgments"] for court in courts]
    assert counts == sorted(counts, reverse=True)  # most judgments first
    assert courts[0] == {"court_code": "ghasc", "court_name": "Supreme Court", "judgments": 90}
