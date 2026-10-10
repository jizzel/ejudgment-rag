from ejudgment.api.export_openapi import DEFAULT_OUT, openapi_schema, render


def test_ui_openapi_snapshot_is_current() -> None:
    """The UI's types are generated from this snapshot; regenerate both when the API changes:
    poetry run python -m ejudgment.api.export_openapi && npm --prefix ui run gen:api"""
    assert DEFAULT_OUT.read_text(encoding="utf-8") == render(openapi_schema())


def test_answer_stream_is_documented_as_server_sent_events() -> None:
    """Clients generated from the contract must read /v1/chat/stream as an event stream (each
    event's data a ChatStreamEventDoc), not as one JSON object; its errors stay JSON."""
    from fastapi.testclient import TestClient

    from ejudgment.api.main import create_app
    from ejudgment.config import Settings

    app = create_app(Settings(), load_models=False)
    for schema in (app.openapi(), TestClient(app).get("/openapi.json").json()):
        responses = schema["paths"]["/v1/chat/stream"]["post"]["responses"]
        assert list(responses["200"]["content"]) == ["text/event-stream"]
        item = responses["200"]["content"]["text/event-stream"]["itemSchema"]
        assert item["required"] == ["event", "data"]
        assert item["properties"]["data"]["contentMediaType"] == "application/json"
        assert item["properties"]["data"]["contentSchema"] == {
            "$ref": "#/components/schemas/ChatStreamEventDoc"
        }
        assert "ChatStreamEventDoc" in schema["components"]["schemas"]
        for status in ("422", "503"):
            assert list(responses[status]["content"]) == ["application/json"]
        plain = schema["paths"]["/v1/chat"]["post"]["responses"]["200"]["content"]
        assert list(plain) == ["application/json"]
