"""Local fake-ICMP results only; no workers, protocol clients or production database."""

import os
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("ipam_manual_fixture.py")))
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402
from sqlalchemy import select  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8237"
settings.cache_clear()
assert "netrix-vlan-browser-" in str(settings().database_url)


def result(reachable):
    with session_factory()() as db:
        row = db.scalar(select(m.IPAddress).where(m.IPAddress.address == "192.0.2.12"))
        vlan = db.get(m.VLAN, row.vlan_id)
        observe(
            db, vlan, row.address, "icmp", vlan.id, {"reachability": "reachable" if reachable else "no_reply"}
        )
        db.commit()
        vlan_id = vlan.id
    services.publish(ping_vlan=vlan_id)
    return {"vlan_id": vlan_id}


result(False)


@main.app.post("/fixture/ping-result")
def fake_ping(reachable: bool):
    return result(reachable)


@main.app.post("/fixture/scan-result")
def fake_scan_result(hostname: str):
    with session_factory()() as db:
        vlan = db.scalar(select(m.VLAN))
        row = observe(db, vlan, "192.0.2.13", "icmp", vlan.id, {"reachability": "reachable"})
        observe(db, vlan, row.address, "dns", vlan.dns_server_id or "system", {"hostname": hostname})
        job = db.scalar(select(m.Job).where(m.Job.kind == "ipam_discover", m.Job.status == "running"))
        if not job:
            job = m.Job(kind="ipam_discover", target_id=vlan.id, status="running", total=254)
            db.add(job)
        job.progress = (job.progress or 0) + 1
        job.result = {"ipam_origin": "schedule", "scan_phase": "addresses"}
        db.commit()
        result = {"vlan_id": vlan.id, "job_id": job.id, "row_id": row.id}
    services.publish(ipam_vlan=result["vlan_id"])
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8237, log_level="warning")
