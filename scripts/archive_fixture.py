"""Archive browser fixture using inventory-origin devices; never runs discovery."""

from netrix.identity.security import encrypt
from sqlalchemy import select

from scripts.inventory_fixture import app, m, session_factory  # noqa: F401

with session_factory()() as db:
    profile = m.Credential(
        name="Archive SNMP fixture", protocol="snmpv2c", encrypted_secret=encrypt('{"community":"fixture"}')
    )
    db.add(profile)
    db.flush()
    scope = m.Scope(
        name="Archive fixture",
        cidr="192.0.2.0/24",
        vrf_id=db.scalar(select(m.VRF.id)),
        credential_id=profile.id,
        vlan_vid=99,
        enabled=False,
    )
    db.add(scope)
    db.flush()
    for device in db.scalars(select(m.Device)):
        device.discovery_scope_id = scope.id
    db.commit()
