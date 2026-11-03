"""Disposable MariaDB: preserve existing IPs, defaults, schema parity and safe rollback."""

import subprocess
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import inspect, text

assert engine().url.database == "netrix_test", "Dedicated disposable database required"
revision = "20261103_38"
previous = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_revision(revision).down_revision


def migrate(*args, blocked=False):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True, text=True)
    if blocked:
        assert result.returncode and "Clear saved manual MAC" in result.stderr, result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", previous)
row_id = str(uuid4())
with session_factory()() as db:
    vrf = m.VRF(name="MAC fixture")
    db.add(vrf)
    db.flush()
    vlan = m.VLAN(name="MAC fixture", vid=20, cidr="192.0.2.0/24", vrf_id=vrf.id)
    db.add(vlan)
    db.flush()
    db.execute(
        text(
            "INSERT INTO ip_addresses (id,address,vrf_id,vlan_id,hostname,status,created_at,updated_at) VALUES (:id,:address,:vrf,:vlan,:hostname,'active',:at,:at)"
        ),
        dict(
            id=row_id,
            address="192.0.2.1",
            vrf=vrf.id,
            vlan=vlan.id,
            hostname="existing.example.test",
            at=now(),
        ),
    )
    db.commit()
migrate("upgrade", "head")
with engine().connect() as conn:
    assert "MariaDB" in conn.scalar(text("SELECT VERSION()"))
    context = MigrationContext.configure(
        conn,
        opts={
            "include_object": lambda obj, name, kind, reflected, compared: (
                kind != "table" or name == "ip_addresses"
            )
        },
    )
    assert not compare_metadata(context, m.Base.metadata)
    column = next(c for c in inspect(conn).get_columns("ip_addresses") if c["name"] == "mac_address")
    assert column["type"].length == 17 and not column["nullable"]
with session_factory()() as db:
    row = db.get(m.IPAddress, row_id)
    assert row.mac_address == "" and row.hostname == "existing.example.test"
    row.mac_address = "02:aa:bb:cc:dd:ee"
    db.commit()
migrate("downgrade", previous, blocked=True)
with session_factory()() as db:
    row = db.get(m.IPAddress, row_id)
    assert row.mac_address == "02:aa:bb:cc:dd:ee"
    row.mac_address = ""
    db.commit()
migrate("downgrade", previous)
assert "mac_address" not in {c["name"] for c in inspect(engine()).get_columns("ip_addresses")}
migrate("upgrade", "head")
with session_factory()() as db:
    row = db.get(m.IPAddress, row_id)
    assert row.mac_address == "" and row.hostname == "existing.example.test"
print("PASS: MariaDB MAC migration, existing rows, default, model parity, protected downgrade and round trip")
