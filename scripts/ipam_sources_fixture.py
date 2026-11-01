"""VLAN source attachment browser fixture; no network collectors run."""

import vlan_configuration_fixture as base
from netrix import models as m
from netrix.core import now, session_factory
from netrix.ipam.service import observe
from sqlalchemy import select

with session_factory()() as db:
    vlan = db.scalar(select(m.VLAN))
    source = m.Integration(
        name="IPAM · HP-SW-BB-01-A-00-01 · 192.0.2.200",
        kind="backbone_switch",
        host="192.0.2.200",
        port=161,
        enabled=True,
        encrypted_secret="fixture",
        last_success_at=now(),
        evidence={
            "hostname": "HP-SW-BB-01-A-00-01",
            "interfaces": [{"name": "H1", "if_index": 225}, {"name": "H3", "if_index": 227}],
            "neighbors": [
                {"interface_name": "H1", "remote_name": "ACCESS-01", "evidence": {}},
                {"interface_name": "H3", "remote_name": "ACCESS-02", "evidence": {}},
            ],
        },
    )
    db.add(source)
    for address, name in [("192.0.2.57", "ACCESS-01"), ("192.0.2.58", "ACCESS-02")]:
        observe(db, vlan, address, "dns", vlan.id, {"hostname": name})
        observe(db, vlan, address, "icmp", vlan.id, {"reachability": "reachable"})
    db.commit()
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(base.main.app, host="127.0.0.1", port=8215, log_level="warning")
