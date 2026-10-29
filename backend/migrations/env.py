from alembic import context
from netrix import models
from netrix.core import Base, engine

config = context.config
with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
