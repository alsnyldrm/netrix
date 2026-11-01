import pytest
from netrix import models as m
from netrix import scheduler
from netrix.ipam import adapters
from sqlalchemy import select
from test_ipam_workspace import integration, prefix
from test_vlan_scan_pipeline import run_scan


@pytest.mark.parametrize("kind", ["corner_switch", "backbone_switch", "firewall"])
def test_network_devices_cannot_be_added_as_integrations(admin_client, kind):
    result = admin_client.post(
        "/api/v1/integrations",
        json={
            "name": "Unsupported",
            "kind": kind,
            "host": "192.0.2.254",
            "port": 161,
            "username": "fixture",
            "password": "fixture",
        },
    )
    assert result.status_code == 422
    assert "kind" in result.text


async def test_vlan_scan_uses_dhcp_and_vmware_without_additional_authorization(
    admin_client, inventory, env, monkeypatch
):
    p = prefix(admin_client, inventory)
    assert "scan_authorized" not in p
    vc = integration(admin_client, p)
    dhcp = integration(admin_client, p, name="DHCP", kind="windows_dhcp", port=5986)
    integration(admin_client, p, name="Disabled", enabled=False)

    async def ping(_):
        return False

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "windows_dhcp", lambda *_: [])
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: [])
    job = admin_client.post(f"/api/v1/ipam/vlans/{p['id']}/discover").json()
    await run_scan(env, monkeypatch, job["id"])
    with env() as db:
        result = db.get(m.Job, job["id"])
        assert result.status == "succeeded"
        assert {db.get(m.Job, id).target_id for id in result.result["source_jobs"]} == {vc["id"], dhcp["id"]}
    saved = admin_client.put(
        f"/api/v1/ipam/vlans/{p['id']}/settings", json={"discovery_enabled": True, "ping_enabled": True}
    )
    assert saved.status_code == 200 and "scan_authorized" not in saved.json()
    scheduler.tick()
    with env() as db:
        assert db.scalar(select(m.Job).where(m.Job.kind == "ipam_ping", m.Job.target_id == p["id"]))
