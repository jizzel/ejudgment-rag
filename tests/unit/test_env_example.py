"""``.env.example`` documents every secret and on/off switch, and only real settings."""

import re

from pydantic import SecretStr

from ejudgment.config import REPO_ROOT, Settings

ENV_EXAMPLE = REPO_ROOT / ".env.example"
# Read by other tools, not by Settings.
NOT_SETTINGS = {"EJUDGMENT_DB_PORT", "HF_HUB_OFFLINE"}
# Must be documented: secrets, switches and anything deployment-specific.
REQUIRED = {
    "DATABASE_URL",
    "AUTH_HASH_SECRET",
    "AUTH_REQUIRED",
    "AUDIT_STORE_RAW_QUERIES",
    "LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OPENAI_ENABLED",
    "OPENAI_API_KEY",
}


def _documented() -> dict[str, str]:
    pairs = re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=(.*)$", ENV_EXAMPLE.read_text(), re.MULTILINE)
    return dict(pairs)


def test_env_example_lists_only_real_settings() -> None:
    fields = {name.upper() for name in Settings.model_fields}
    unknown = set(_documented()) - fields - NOT_SETTINGS
    assert not unknown, f".env.example names variables Settings does not read: {unknown}"


def test_env_example_covers_every_secret_and_switch() -> None:
    secrets = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if SecretStr in getattr(field.annotation, "__args__", (field.annotation,))
    }
    missing = (REQUIRED | secrets) - set(_documented())
    assert not missing, f"add these to .env.example: {missing}"


def test_env_example_holds_no_real_secrets() -> None:
    values = _documented()
    assert values["OPENAI_API_KEY"] == "sk-..."
    assert values["AUTH_HASH_SECRET"].startswith("change-me")
