"""Disposable one-IP browser fixture. Every protocol is replaced before the worker runs."""

import os
import runpy
from pathlib import Path
from types import SimpleNamespace

runpy.run_path(str(Path(__file__).with_name("ipam_manual_fixture.py")))
from netrix import main, worker  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.ipam import adapters  # noqa: E402
from sqlalchemy import select  # noqa: E402

PORT = int(os.environ.get("NETRIX_ADDRESS_FIXTURE_PORT", "8242"))
os.environ["NETRIX_PUBLIC_URL"] = f"http://127.0.0.1:{PORT}"
settings.cache_clear()
assert "netrix-vlan-browser-" in str(settings().database_url)
with session_factory()() as db:
    row = db.scalar(select(m.IPAddress).where(m.IPAddress.address == "192.0.2.12"))
    row.hostname = ""
    for device in db.scalars(select(m.Device)):
        device.snmp_credential_id = None
    for config in db.scalars(select(m.Integration)):
        config.enabled = False
    db.commit()


@main.app.post("/fixture/run-address-job")
async def run_address_job():
    pinged, resolved = [], []

    async def ping(address):
        pinged.append(address)
        return True

    async def dns(address, server):
        resolved.append(address)
        return "scanned-12.example.test"

    async def forbidden(*args):
        raise AssertionError("The browser fixture must never contact devices")

    adapters.ping, adapters.reverse_dns = ping, dns
    adapters.vcenter_records = adapters.windows_dhcp = lambda *_: (_ for _ in ()).throw(
        AssertionError("No integration reads in browser fixture")
    )
    id = worker.claim(interactive=False, include_kinds=("ipam_address_scan",))
    assert id
    await worker.execute(id, SimpleNamespace(ipam=forbidden))
    return {"job_id": id, "pinged": pinged, "resolved": resolved}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=PORT, log_level="warning")
