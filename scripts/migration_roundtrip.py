"""Destructive schema test restricted to the explicitly named disposable database."""

import subprocess

from netrix.core import engine

assert engine().url.database == "netrix_test", "Only the disposable netrix_test database is allowed"
for arguments in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"], ["check"]):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", *arguments], check=True)
print("Disposable migration round-trip PASS")
