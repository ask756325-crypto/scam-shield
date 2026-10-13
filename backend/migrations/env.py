"""Alembic environment: uses the application's engine/URL and models, so migrations always match the app config."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (register every model on Base.metadata)
from app.db import Base, engine

config = context.config
if config.config_file_name and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=engine.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.connect() as conn:
        _run(conn)


def _run(conn) -> None:
    # render_as_batch: SQLite cannot ALTER most constraints in place; batch mode recreates the table safely.
    context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=conn.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
