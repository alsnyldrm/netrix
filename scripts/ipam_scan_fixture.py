"""Local-only scheduling fixture; no worker and no real device access."""

import os
import runpy
from datetime import datetime
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("vlan_configuration_fixture.py")))

from netrix import main  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.ipam.scan_schedules import dispatch_due  # noqa: E402
from sqlalchemy import select  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8225"
settings.cache_clear()
with session_factory()() as db:
    first = db.scalar(select(m.VLAN))
    db.add(m.VLAN(name="NETWORK", vid=10, domain="fixture", cidr="198.51.100.0/30", vrf_id=first.vrf_id))
    db.add(m.VLAN(name="CIDR eksik", vid=30, domain="fixture", vrf_id=first.vrf_id))
    db.commit()


@main.app.post("/fixture/dispatch")
def dispatch(at: str):
    dispatch_due(datetime.fromisoformat(at))
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8225, log_level="warning")
