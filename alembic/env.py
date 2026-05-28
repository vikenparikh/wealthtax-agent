"""Alembic environment that reflects the SQLAlchemy metadata defined in
``wealthtax_agent.db.models``. We override sqlalchemy.url from the env so
both SQLite (dev) and Postgres (prod) share the same migration history.
"""

from logging.config import fileConfig
import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make ``src/`` importable so we can pull in our metadata.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wealthtax_agent.db import Base  # noqa: E402
from wealthtax_agent.db import models  # noqa: F401, E402  - registers tables

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False so our app loggers (e.g.
    # wealthtax_agent.llm / .graph / .build_return) keep their handlers when
    # tests run `alembic upgrade head` mid-suite.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

env_url = os.getenv("DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
