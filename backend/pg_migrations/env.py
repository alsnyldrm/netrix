from alembic import context
from netrix import models  # noqa: F401
from netrix.core import Base, settings
from sqlalchemy import create_engine, text

url = settings().migration_database_url or settings().database_url
with create_engine(url, hide_parameters=True).connect() as connection:
    if connection.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL migrations require PostgreSQL")
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS yonetim"))
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        version_table_schema="yonetim",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
