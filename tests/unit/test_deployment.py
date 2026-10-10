"""Deployment configuration: database URL from parts, image contents, backup settings."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from ejudgment.config import REPO_ROOT, Settings

TRICKY = "p@ss/w:rd%40#?&= $x"


def test_container_database_url_encodes_any_password() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dev:dev@localhost:5434/dev",
        postgres_host="postgres",
        postgres_password=SecretStr(TRICKY),
    )
    url = make_url(settings.database_url)
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "ejudgment",
        TRICKY,
        "postgres",
        5432,
        "ejudgment",
    )


def test_host_side_database_url_is_used_without_postgres_host() -> None:
    dev = "postgresql+psycopg://dev:dev@localhost:5434/dev"
    settings = Settings(database_url=dev, postgres_password=SecretStr("only-for-compose"))
    assert settings.database_url == dev


def test_compose_passes_the_password_not_a_url() -> None:
    """A password with @ or / inside a URL would break it; the app builds the URL itself."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    environment = compose["x-python"]["environment"]
    assert "DATABASE_URL" not in environment
    assert environment["POSTGRES_HOST"] == "postgres"
    assert "POSTGRES_PASSWORD" in environment


def test_the_image_contains_what_the_workers_read_by_default() -> None:
    dockerfile = (REPO_ROOT / "docker" / "python.Dockerfile").read_text()
    copied = set(re.findall(r"^COPY (?!--from)(\S+)", dockerfile, re.MULTILINE))
    for needed in ("alembic.ini", "migrations", "config", "evals", "src"):
        assert needed in copied, f"docker/python.Dockerfile must COPY {needed}"
    # The default gold set path (relative to the image's /app) exists in the repository.
    assert (REPO_ROOT / "evals" / "gold.jsonl").is_file()


def _lib(env_file: Path, **exported: str) -> str:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("BACKUP_")}
    environment.update(exported, ENV_FILE=str(env_file))
    result = subprocess.run(
        ["bash", "-c", 'source scripts/lib.sh && printf "%s|%s" "$BACKUP_DIR" "$BACKUP_KEEP"'],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_backup_settings_come_from_env_file_unless_exported(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# BACKUP_KEEP=99\n"
        "BACKUP_DIR='/srv/backups'\n"
        "OTHER=$(echo would-run-if-sourced)\n"  # never executed: .env is not sourced
        "BACKUP_KEEP = 30 \n"
    )
    assert _lib(env_file) == "/srv/backups|30"
    assert _lib(env_file, BACKUP_KEEP="7") == "/srv/backups|7"  # exported wins
    assert _lib(tmp_path / "missing.env") == "backups|14"  # defaults


@pytest.mark.parametrize("keep", ["abc", "0", "-1", "3.5"])
def test_backup_refuses_a_bad_keep_count_before_doing_anything(keep: str) -> None:
    environment = dict(os.environ, BACKUP_KEEP=keep, COMPOSE="false")  # no docker call possible
    result = subprocess.run(
        ["bash", "scripts/backup.sh", "/nonexistent-dir-should-not-be-created"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "BACKUP_KEEP must be a positive integer" in result.stderr
    assert not Path("/nonexistent-dir-should-not-be-created").exists()
