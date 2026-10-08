from alembic.config import Config

from ejudgment.db import alembic_ini_value

URL = "postgresql+psycopg://user:p%40ss%25word@localhost:5434/ejudgment"


def test_alembic_ini_value_round_trips_percent_encoded_credentials() -> None:
    config = Config()
    config.set_main_option("sqlalchemy.url", alembic_ini_value(URL))
    assert config.get_main_option("sqlalchemy.url") == URL


def test_alembic_ini_value_leaves_plain_urls_unchanged() -> None:
    plain = "postgresql+psycopg://ejudgment:ejudgment@localhost:5434/ejudgment"
    assert alembic_ini_value(plain) == plain
