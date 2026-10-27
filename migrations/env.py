from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from ozon_sync.config import Settings

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def _url() -> str:
    return Settings().database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
