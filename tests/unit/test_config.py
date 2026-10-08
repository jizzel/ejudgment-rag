from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from ejudgment.config import Settings


def _settings_with_yaml(yaml_file: Path) -> Settings:
    class YamlSettings(Settings):
        model_config = SettingsConfigDict(yaml_file=yaml_file, env_file=None)

    return YamlSettings()


def test_defaults_apply_without_yaml_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INGEST_BATCH_SIZE", raising=False)
    settings = _settings_with_yaml(tmp_path / "absent.yaml")
    assert settings.ingest_batch_size == 200


def test_yaml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INGEST_BATCH_SIZE", raising=False)
    yaml_file = tmp_path / "models.yaml"
    yaml_file.write_text("ingest_batch_size: 50\n")
    assert _settings_with_yaml(yaml_file).ingest_batch_size == 50


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_file = tmp_path / "models.yaml"
    yaml_file.write_text("ingest_batch_size: 50\n")
    monkeypatch.setenv("INGEST_BATCH_SIZE", "7")
    assert _settings_with_yaml(yaml_file).ingest_batch_size == 7


def test_repo_yaml_is_valid() -> None:
    Settings()
