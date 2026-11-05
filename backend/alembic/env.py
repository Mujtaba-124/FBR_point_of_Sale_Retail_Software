from logging.config import fileConfig

from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (register models on Base.metadata)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    # Keep application loggers alive when migrations run in-process (tests).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
# An explicit URL (used by the test suite for its disposable database) wins.
DATABASE_URL = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
