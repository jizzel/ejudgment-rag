"""API behaviour when PostgreSQL is unreachable (no database needed)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ejudgment.api.main import create_app
from ejudgment.config import Settings


@pytest.fixture
def offline_client(settings: Settings) -> Iterator[TestClient]:
    # Nothing listens on port 1: every connection attempt fails immediately.
    unreachable = create_engine("postgresql+psycopg://nobody:secret@127.0.0.1:1/none")
    with TestClient(create_app(settings, unreachable, load_models=False)) as test_client:
        yield test_client
    unreachable.dispose()


def test_healthz_reports_database_outage_as_503(offline_client: TestClient) -> None:
    response = offline_client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


def test_other_routes_report_database_outage_as_503(offline_client: TestClient) -> None:
    for response in (
        offline_client.post("/v1/search", json={"query": "contract"}),
        offline_client.get("/v1/judgments/00000000-0000-0000-0000-000000000000"),
    ):
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "database_unavailable"
        assert "secret" not in response.text and "nobody" not in response.text
