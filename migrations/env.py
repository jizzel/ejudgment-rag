from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ejudgment.config import get_settings
from ejudgment.db import alembic_ini_value
from ejudgment.domain.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# An explicitly set URL (e.g. from tests) wins; otherwise use application settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", alembic_ini_value(get_settings().database_url))

target_metadata = Base.metadata

# Per-model HNSW expression indexes are managed by hand in migrations (one per embedding
# model/revision); SQLAlchemy metadata cannot express them, so autogenerate ignores them.
MANAGED_INDEX_PREFIX = "ix_chunk_embeddings_hnsw_"


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "index" and name is not None and name.startswith(MANAGED_INDEX_PREFIX))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
