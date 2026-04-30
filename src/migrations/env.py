"""Alembic async migration environment for ArXivAgent.

Uses SQLAlchemy asyncpg driver — runs migrations via connection.run_sync()
so Alembic's synchronous context.run_migrations() executes on an unwrapped
synchronous connection while the outer event loop remains async.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from src.config import get_settings  # noqa: E402
from src.db.models import Base  # noqa: E402

# Override the placeholder URL with the real DATABASE_URL from environment.
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection.

    Useful for generating migration scripts to review or apply manually.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Configure Alembic context and run migrations on a synchronous connection.

    Called via connection.run_sync() — SQLAlchemy unwraps the async connection
    and passes a plain synchronous Connection here.

    Args:
        connection: Synchronous SQLAlchemy Connection provided by run_sync.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create a poolless async engine from alembic.ini and apply migrations.

    NullPool prevents idle connections from being held open between steps.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a live database (the normal path)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
