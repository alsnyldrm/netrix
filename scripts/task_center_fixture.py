"""Local task-center browser fixture, with no running workers or network scans."""

from datetime import timedelta

from inventory_fixture import app  # noqa: F401
from netrix import models as m
from netrix.core import now, session_factory
from netrix.identity.security import encrypt
from sqlalchemy import select

with session_factory()() as db:
    credential = m.Credential(
        name="Merkez SNMP", protocol="snmpv2c", encrypted_secret=encrypt('{"community":"fixture"}')
    )
    db.add(credential)
    db.flush()
    vrf = db.scalar(select(m.VRF))
    scope = m.Scope(name="VLAN-60", cidr="10.6.0.0/21", vrf_id=vrf.id, credential_id=credential.id)
    prefix = m.Prefix(cidr="10.6.0.0/21", vrf_id=vrf.id)
    db.add_all([scope, prefix])
    db.flush()
    db.add_all(
        [
            m.Job(
                kind="discovery",
                target_id=scope.id,
                status="running",
                progress=96,
                total=2046,
                attempts=1,
                created_at=now() - timedelta(seconds=30),
                result={"started_at": (now() - timedelta(seconds=29)).isoformat()},
            ),
            m.Job(
                kind="ipam_ping",
                target_id=prefix.id,
                status="succeeded",
                progress=10,
                total=10,
                attempts=1,
                finished_at=now(),
                result={"reachable": 8, "no_reply": 2},
            ),
        ]
    )
    db.commit()
