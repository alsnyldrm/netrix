"""Neighbor evidence round trip on a disposable MariaDB netrix_test database only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.discovery.links import sync_links
from sqlalchemy import insert, text

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "20261030_08")
with session_factory()() as db:
    db.execute(insert(m.VRF.__table__).values(id="neighbor-vrf", name="Neighbor test"))
    db.execute(
        insert(m.Device.__table__).values(
            id="neighbor-core", name="core", management_ip="192.0.2.1", vrf_id="neighbor-vrf"
        )
    )
    db.execute(
        text("""INSERT INTO topology_links
        (id, device_id, interface_name, remote_name, remote_port, source, confidence, created_at, updated_at)
        VALUES ('legacy-neighbor', 'neighbor-core', 'H3', :raw, '49', 'cdp', 0.5, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))"""),
        {"raw": bytes.fromhex("3821c73cb240").decode("latin1")},
    )
    db.commit()
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    link = db.get(m.Link, "legacy-neighbor")
    assert link.is_current and link.evidence == {} and link.last_seen_at.tzinfo
    sync_links(
        db,
        db.get(m.Device, "neighbor-core"),
        {
            "neighbors": [
                {
                    "interface_name": "H3",
                    "remote_name": "edge",
                    "remote_port": "49",
                    "source": "lldp+cdp",
                    "evidence": {
                        "cdp": {
                            "device_id_hex": "3821c73cb240",
                            "device_id": "38:21:c7:3c:b2:40",
                            "port_id": "49",
                        }
                    },
                }
            ],
            "neighbor_protocols_complete": ["lldp", "cdp"],
        },
    )
    db.commit()
    assert link.remote_name == "edge" and link.evidence["cdp"]["device_id"] == "38:21:c7:3c:b2:40"
    observed = link.last_seen_at
    sync_links(
        db,
        db.get(m.Device, "neighbor-core"),
        {"neighbors": [], "neighbor_protocols_complete": ["lldp", "cdp"]},
    )
    db.commit()
    db.refresh(link)
    assert not link.is_current and link.last_seen_at == observed
assert migrate("downgrade", "20261030_08", check=False).returncode != 0
# Only the disposable fixture is cleared to exercise the guarded round trip.
with session_factory()() as db:
    db.execute(text("UPDATE topology_links SET evidence = '{}', is_current = 1"))
    db.commit()
migrate("downgrade", "20261030_08")
migrate("upgrade", "head")
migrate("check")
print(
    "MariaDB neighbor evidence PASS: legacy data, current flags, UTC, reconciliation, history, guarded downgrade, round trip, schema"
)
