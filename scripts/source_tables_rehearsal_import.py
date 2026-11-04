"""Consume the explicit trusted in-host rehearsal stream into a disposable SQL DB."""

import pickle
import sys

from netrix import models as m
from netrix.core import Base, engine
from sqlalchemy import text

assert engine().url.database == "netrix_test"
Base.metadata.create_all(engine())
with engine().begin() as c:
    c.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    batch, current = [], None
    while True:
        message = pickle.load(sys.stdin.buffer)
        if message is None:
            break
        name, row = message
        if current and (current != name or len(batch) == 250):
            c.execute(m.Base.metadata.tables[current].insert(), batch)
            batch = []
        current = name
        batch.append(row)
    if batch:
        c.execute(m.Base.metadata.tables[current].insert(), batch)
    c.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    c.execute(text("INSERT INTO alembic_version VALUES ('20261104_49')"))
print("Current source rehearsal imported into tmpfs MariaDB; no dump file")
