"""Database engine construction."""

from sqlalchemy import Engine, create_engine

from ejudgment.config import Settings


def alembic_ini_value(url: str) -> str:
    """Escape a database URL for Alembic's ConfigParser-backed options.

    ConfigParser treats ``%`` as interpolation, so percent-encoded credentials such as
    ``p%40ss`` would otherwise raise ``ValueError`` in ``set_main_option``.
    """
    return url.replace("%", "%%")


def make_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)
