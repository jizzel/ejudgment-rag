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


# --- restore.sh against a fake Postgres ------------------------------------------------------

STUB = r"""#!/usr/bin/env bash
# Fake "docker compose": logs every client command run in the postgres container.
shift 3                                   # "exec -T postgres"
echo "$*" >>"$STUB_LOG"
case "$1" in
  pg_restore)
    cat >/dev/null
    [[ "${STUB_RESTORE_FAIL:-0}" == 1 ]] && { echo "pg_restore: error: disk full" >&2; exit 1; }
    ;;
  psql)
    case "$*" in
      *pg_tables*) echo "${STUB_TABLES:-0}" ;;
      *count*) [[ "${STUB_COUNT_FAIL:-0}" == 1 ]] && exit 1; echo 1 ;;
      *version_num*) echo 0008 ;;
    esac
    ;;
esac
exit 0
"""


def _restore(tmp_path: Path, *args: str, **env: str) -> tuple[int, str, str]:
    stub = tmp_path / "fake-compose.sh"
    stub.write_text(STUB)
    dump = tmp_path / "ejudgment-x.dump"
    dump.write_bytes(b"not really a dump")
    digest = subprocess.run(
        ["shasum", "-a", "256", dump.name], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout
    (tmp_path / "ejudgment-x.dump.sha256").write_text(digest)
    log = tmp_path / "calls.log"
    log.write_text("")
    environment = dict(os.environ, COMPOSE=f"bash {stub}", STUB_LOG=str(log), **env)
    result = subprocess.run(
        ["bash", "scripts/restore.sh", str(dump), *args],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    return result.returncode, log.read_text(), result.stderr


def test_failed_restore_into_empty_live_db_is_reset(tmp_path: Path) -> None:
    code, calls, stderr = _restore(tmp_path, "ejudgment", "--into-empty", STUB_RESTORE_FAIL="1")
    assert code != 0 and "restore failed" in stderr
    assert "DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION ejudgment" in calls
    assert "dropdb" not in calls  # the live database itself is never dropped


def test_failed_restore_into_new_db_drops_only_that_db(tmp_path: Path) -> None:
    code, calls, _ = _restore(tmp_path, "ejudgment_restore_t", STUB_RESTORE_FAIL="1")
    assert code != 0
    lines = calls.splitlines()
    assert lines[0] == "createdb -U ejudgment ejudgment_restore_t"
    assert lines[-1] == "dropdb -U ejudgment --if-exists ejudgment_restore_t"
    assert "DROP SCHEMA" not in calls


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (("ejudgment",), {}),  # live database without --into-empty
        (("ejudgment", "--into-empty"), {"STUB_TABLES": "3"}),  # not empty
    ],
)
def test_refused_restores_clean_up_nothing(
    tmp_path: Path, args: tuple[str, ...], env: dict[str, str]
) -> None:
    code, calls, _ = _restore(tmp_path, *args, STUB_RESTORE_FAIL="1", **env)
    assert code == 2
    for command in ("pg_restore", "DROP SCHEMA", "dropdb", "createdb"):
        assert command not in calls


def test_successful_restore_is_never_undone(tmp_path: Path) -> None:
    code, calls, _ = _restore(tmp_path, "ejudgment_restore_t")
    assert code == 0
    assert "pg_restore" in calls and "dropdb" not in calls
    # Even if a later step (the row-count summary) fails, the restored data stays.
    code, calls, _ = _restore(tmp_path, "ejudgment_restore_t", STUB_COUNT_FAIL="1")
    assert code != 0 and "pg_restore" in calls and "dropdb" not in calls


def test_restore_drill_compares_every_application_table() -> None:
    from ejudgment.domain.models import Base

    lib = (REPO_ROOT / "scripts" / "lib.sh").read_text()
    listed = set(re.search(r"DRILL_TABLES=\(([^)]*)\)", lib).group(1).split())  # type: ignore[union-attr]
    assert listed == set(Base.metadata.tables), "keep DRILL_TABLES in scripts/lib.sh in step"


def test_backup_keeps_only_the_newest_dumps(tmp_path: Path) -> None:
    stub = tmp_path / "fake-compose.sh"
    stub.write_text('#!/usr/bin/env bash\nshift 3\necho "dump bytes for $*"\n')
    backups = tmp_path / "backups"
    backups.mkdir()
    old = [f"ejudgment-2026010{day}T020000Z.dump" for day in range(1, 6)]
    for name in old:
        (backups / name).write_text("old")
        (backups / f"{name}.sha256").write_text("x")
    environment = dict(os.environ, COMPOSE=f"bash {stub}", BACKUP_KEEP="3")
    result = subprocess.run(
        ["bash", "scripts/backup.sh", str(backups)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    new = Path(result.stdout.strip()).name
    kept = sorted(p.name for p in backups.glob("*.dump"))
    assert kept == [old[3], old[4], new]  # the newest three by timestamp
    assert sorted(p.name for p in backups.glob("*.sha256")) == [f"{n}.sha256" for n in kept]
    assert (backups / new).read_text().startswith("dump bytes for pg_dump")


def test_image_and_ci_install_dependencies_the_same_way() -> None:
    """One CPU-only torch install method (scripts/install-python-deps.sh) for both."""
    dockerfile = (REPO_ROOT / "docker" / "python.Dockerfile").read_text()
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "bash scripts/install-python-deps.sh /opt/venv" in dockerfile
    assert "bash scripts/install-python-deps.sh .venv --with-dev" in workflow
    assert "EJUDGMENT_REQUIRE_DB" in workflow  # integration tests may not skip in CI
