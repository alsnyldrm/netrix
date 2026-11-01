"""Seed the old schema using the previous application image, disposable DB only."""

from datetime import timedelta

from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.identity.security import encrypt

assert engine().url.database == "netrix_test"
with session_factory()() as db:
    from netrix.inventory.device_types import seed_defaults

    seed_defaults(db)
    vrf = m.VRF(name="Global")
    db.add(vrf)
    db.flush()
    credential = m.Credential(
        id="fixture-credential",
        name="Fixture SNMP",
        protocol="snmpv2c",
        encrypted_secret=encrypt('{"community":"fixture"}'),
    )
    vlan = m.VLAN(id="fixture-vlan", name="Servers", vid=20)
    db.add_all([credential, vlan])
    db.flush()
    scope = m.Scope(
        id="fixture-scope",
        name="Inventory network",
        cidr="192.0.2.0/24",
        vrf_id=vrf.id,
        credential_id=credential.id,
    )
    db.add(scope)
    db.flush()
    prefix = m.Prefix(
        id="fixture-prefix",
        cidr="192.0.2.0/24",
        vrf_id=vrf.id,
        vlan_id=vlan.id,
        scope_id=scope.id,
        scan_authorized=True,
        warning_threshold=75,
    )
    d = m.Device(
        id="fixture-device",
        name="Corner fixture",
        kind="switch",
        management_ip="192.0.2.254",
        vrf_id=vrf.id,
        snmp_credential_id=credential.id,
    )
    db.add_all([prefix, d])
    db.flush()
    db.add(
        m.IPAddress(
            id="fixture-address",
            address="192.0.2.2",
            prefix_id=prefix.id,
            vrf_id=vrf.id,
            hostname="preserved",
        )
    )
    for i, content in enumerate(
        [
            "!Version AOS-CX PL.10.17.1030\nhostname fixture",
            "!Version AOS-CX PL.10.18.1000\nhostname fixture",
            "!Version AOS-CX PL.10.18.1000\nhostname actual-change",
        ]
    ):
        job = m.Job(id=f"fixture-job-{i}", kind="backup", target_id=d.id, status="succeeded")
        db.add(job)
        db.flush()
        db.add(
            m.Snapshot(
                id=f"fixture-snapshot-{i}",
                device_id=d.id,
                job_id=job.id,
                encrypted_content=encrypt(content),
                fingerprint="0" * 64,
                size_bytes=len(content),
                created_at=now() + timedelta(minutes=i),
                changed=i > 0,
            )
        )
    db.commit()
print("Old-schema fixtures ready")
