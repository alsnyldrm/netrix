"""Multi-NIC browser evidence, entirely isolated from real devices."""

import ipam_fixture as fixture
from netrix import models as m
from netrix.core import now, session_factory
from sqlalchemy import select

with session_factory()() as db:
    prefix = db.scalar(select(m.Prefix))
    devices = []
    for i in [1, 2]:
        device = m.Device(
            name=f"HP-SW-BB-01-A-00-0{i}",
            management_ip=f"192.0.2.{250 + i}",
            vrf_id=prefix.vrf_id,
            kind="fixture-backbone",
        )
        db.add(device)
        db.flush()
        devices.append(device)
    for address, host, pairs in [
        ("192.0.2.55", "SV-VW-05", [(0, "A7"), (0, "B7")]),
        ("192.0.2.56", "SV-VW-06", [(0, "I5"), (1, "A6")]),
    ]:
        row = m.IPAddress(address=address, hostname=host, vrf_id=prefix.vrf_id, prefix_id=prefix.id)
        db.add(row)
        for n, (device, port) in enumerate(pairs):
            db.add(
                m.Interface(
                    device_id=devices[device].id,
                    name=port,
                    if_index=int(address.split(".")[-1]) * 10 + n,
                    is_managed=True,
                )
            )
            db.add(
                m.Link(
                    device_id=devices[device].id,
                    interface_name=port,
                    remote_name=host,
                    remote_port=port,
                    manual_remote_name=host,
                    last_seen_at=now(),
                )
            )
    db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(fixture.main.app, host="127.0.0.1", port=8211, log_level="warning")
