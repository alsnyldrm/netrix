"""Local transfer browser fixture with fake probes; never imported by production."""

from fastapi import Depends
from netrix import models as m
from netrix import worker
from netrix.core import session_factory
from netrix.identity.security import encrypt, operator
from sqlalchemy import select

from scripts.inventory_fixture import app

with session_factory()() as db:
    vrf = db.scalar(select(m.VRF))
    profile = m.Credential(
        name="Fixture SNMP",
        protocol="snmpv3",
        encrypted_secret=encrypt(
            '{"username":"fixture","auth_key":"fixture-auth","priv_key":"fixture-priv"}'
        ),
    )
    db.add(profile)
    db.flush()
    db.add(m.Scope(name="Local fixture only", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=profile.id))
    db.commit()


async def fake_probe(device, protocol, secret, collector):
    if device.management_ip.endswith((".102", ".112")):
        raise TimeoutError("fixture-password")
    return "Bağlantı başarılı (yerel test istemcisi)."


worker.probe_connection = fake_probe


@app.post("/_fixture/complete-tests")
async def complete_tests(user=Depends(operator)):
    with session_factory()() as db:
        for job in db.scalars(select(m.Job).where(m.Job.kind == "identify")):
            job.status, job.active_key = "cancelled", None
        db.commit()
    while job_id := worker.claim():
        await worker.execute(job_id)
    return {"completed": True}
