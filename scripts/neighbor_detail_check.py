"""MariaDB JSON/unique-key validation, exclusively in a disposable netrix_test database."""

import subprocess

from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.discovery.links import repair_stored_ports, sync_links
from sqlalchemy import select

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    vrf = m.VRF(name="detail fixture")
    db.add(vrf)
    db.flush()
    local = m.Device(name="edge", management_ip="192.0.2.20", vrf_id=vrf.id)
    peer = m.Device(name="managed core", management_ip="192.0.2.21", vrf_id=vrf.id)
    db.add_all([local, peer])
    db.flush()
    evidence = {
        "lldp": {
            "port_subtype": 7,
            "port_id": "260",
            "port_description": "I4",
            "chassis_id": "08:f1:ea:65:42:00",
        },
        "cdp": {"port_id": "I4", "management_address": "192.0.2.21"},
    }
    legacy = m.Link(
        device_id=local.id,
        interface_name="A1",
        remote_name="core",
        remote_port="260",
        source="lldp+cdp",
        evidence=evidence,
        last_seen_at=now(),
    )
    duplicate = m.Link(
        device_id=local.id,
        interface_name="B1",
        remote_name="core",
        remote_port="260",
        source="lldp",
        evidence=evidence,
    )
    canonical = m.Link(
        device_id=local.id,
        interface_name="B1",
        remote_name="core",
        remote_port="I4",
        source="cdp",
        evidence=evidence,
    )
    db.add_all([legacy, duplicate, canonical])
    db.commit()
    stamp = legacy.last_seen_at
    assert repair_stored_ports(db) == {"corrected_ports": 1, "retired_duplicates": 1}
    db.commit()
    assert legacy.last_seen_at == stamp and legacy.remote_port == "I4"
    assert not duplicate.is_current and canonical.is_current
    assert repair_stored_ports(db) == {"corrected_ports": 0, "retired_duplicates": 0}
    sync_links(
        db,
        local,
        {
            "neighbors": [
                {
                    "interface_name": "A1",
                    "remote_name": "core",
                    "remote_port": "I4",
                    "source": "lldp+cdp",
                    "evidence": evidence,
                }
            ]
        },
    )
    db.commit()
    assert legacy.remote_device_id == peer.id and legacy.confidence == 0.9
    assert len(list(db.scalars(select(m.Link)))) == 3
print(
    "MariaDB neighbor detail PASS: evidence labels, duplicate retirement, original observation time, idempotence, IP matching"
)
