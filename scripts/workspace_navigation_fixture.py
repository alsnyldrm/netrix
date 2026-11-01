"""Isolated navigation/refresh fixture; no workers, Redis service or device traffic."""

import runpy

fixture = runpy.run_path("scripts/vlan_configuration_fixture.py", run_name="fixture")
app = fixture["main"].app
m, sf = fixture["m"], fixture["session_factory"]

with sf()() as db:
    from netrix.ipam.service import observe
    from sqlalchemy import select

    row = db.scalar(select(m.IPAddress).where(m.IPAddress.address == "192.0.2.10"))
    vlan = db.get(m.VLAN, row.vlan_id)
    observe(db, vlan, row.address, "dns", vlan.dns_server_id, {"hostname": "app-01.example.test"})
    db.commit()


@app.post("/fixture/change-hostname")
def change_hostname():
    from netrix.ipam.service import observe
    from sqlalchemy import select

    with sf()() as db:
        row = db.scalar(select(m.IPAddress).where(m.IPAddress.address == "192.0.2.10"))
        vlan = db.get(m.VLAN, row.vlan_id)
        observe(
            db,
            vlan,
            row.address,
            "dns",
            vlan.dns_server_id or "system",
            {"hostname": "refreshed.example.test"},
        )
        db.commit()  # Simulate an external update without the notification bus.
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8215, log_level="warning")
