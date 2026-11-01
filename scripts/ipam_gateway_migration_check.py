"""Gateway flag upgrade/default/downgrade on a disposable MariaDB only."""

import subprocess

from netrix.core import engine
from sqlalchemy import text

assert engine().url.database == "netrix_test"


def migrate(action, revision):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", action, revision], check=True)


migrate("upgrade", "20261101_25")
with engine().begin() as db:
    db.execute(
        text(
            "INSERT INTO vrfs (id,name,description,lock_version,created_at,updated_at) VALUES ('vrf','Fixture','',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    db.execute(
        text(
            "INSERT INTO vlans (id,name,domain,vid,vrf_id,cidr,created_at,updated_at) VALUES ('vlan','Fixture','fixture',123,'vrf','192.0.2.0/24',UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    db.execute(
        text(
            "INSERT INTO ip_addresses (id,address,vrf_id,vlan_id,status,hostname,created_at,updated_at) VALUES ('ip','192.0.2.1','vrf','vlan','active','Retained',UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
migrate("upgrade", "head")
with engine().begin() as db:
    assert db.scalar(text("SELECT is_gateway FROM ip_addresses WHERE id='ip'")) == 0
    db.execute(text("UPDATE ip_addresses SET is_gateway=1 WHERE id='ip'"))
with engine().connect() as db:
    assert db.scalar(text("SELECT is_gateway FROM ip_addresses WHERE id='ip'")) == 1
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
migrate("downgrade", "20261101_25")
with engine().connect() as db:
    assert db.scalar(text("SELECT hostname FROM ip_addresses WHERE id='ip'")) == "Retained"
migrate("upgrade", "head")
with engine().connect() as db:
    assert db.scalar(text("SELECT is_gateway FROM ip_addresses WHERE id='ip'")) == 0
print("PASS: existing IP preserved, default false, saved true, schema parity, downgrade and upgrade")
