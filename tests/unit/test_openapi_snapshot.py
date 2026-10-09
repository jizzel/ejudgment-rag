from ejudgment.api.export_openapi import DEFAULT_OUT, openapi_schema, render


def test_ui_openapi_snapshot_is_current() -> None:
    """The UI's types are generated from this snapshot; regenerate both when the API changes:
    poetry run python -m ejudgment.api.export_openapi && npm --prefix ui run gen:api"""
    assert DEFAULT_OUT.read_text(encoding="utf-8") == render(openapi_schema())
