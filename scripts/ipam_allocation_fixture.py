"""Disposable SQL-only manual IP creation fixture; no protocol workers."""

import os
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("ipam_manual_fixture.py")))

from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402
from sqlalchemy import select  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8247"
settings.cache_clear()


def no_job(*args, **kwargs):
    raise AssertionError("Manual IP creation must never enqueue a scan")


services.enqueue = no_job
with session_factory()() as db:
    vlan = db.scalar(select(m.VLAN))
    db.scalar(select(m.Interface).where(m.Interface.name == "1/1/7")).is_managed = True
    observe(db, vlan, "192.0.2.13", "icmp", vlan.id, {"reachability": "no_reply"})
    db.add(m.IPAddress(address="192.0.2.14", vrf_id=vlan.vrf_id, vlan_id=vlan.id, status="reserved"))
    db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8247, log_level="warning")
