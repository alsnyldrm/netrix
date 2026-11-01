"""Connection views must use inventory membership, not the shared IPAM device table."""

import json

import pytest
from conftest import make_inventory_scope
from netrix import models as m
from netrix.discovery.manual_links import confirm_link
from sqlalchemy import select


@pytest.fixture
def mixed_devices(admin_client, env):
    with env() as db:
        vrf = db.scalar(select(m.VRF))
        scope = make_inventory_scope(db, vrf.id)
        devices = {
            name: m.Device(
                name=name,
                management_ip=f"192.0.2.{i}",
                vrf_id=vrf.id,
                kind="server" if "server" in name else "switch",
                discovery_scope_id=scope.id if name.startswith("inventory") else None,
            )
            for i, name in enumerate(("inventory-core", "inventory-server", "ipam-server"), 1)
        }
        db.add_all(devices.values())
        db.flush()
        links = {}
        for i, (name, local, remote, deleted) in enumerate(
            [
                ("valid", "inventory-core", "inventory-server", False),
                ("outgoing-ipam", "inventory-core", "ipam-server", False),
                ("incoming-ipam", "ipam-server", "inventory-core", False),
                ("deleted-valid", "inventory-core", "inventory-server", True),
                ("deleted-ipam", "ipam-server", "inventory-core", True),
                ("deleted-remote-ipam", "inventory-core", "ipam-server", True),
            ]
        ):
            links[name] = m.Link(
                device_id=devices[local].id,
                remote_device_id=devices[remote].id,
                interface_name=str(i),
                remote_name=remote,
                remote_port="1",
                source="lldp",
                is_current=not deleted,
                auto_add_excluded=deleted,
            )
        db.add_all(links.values())
        db.commit()
        return {
            "devices": {k: d.id for k, d in devices.items()},
            "links": {k: l.id for k, l in links.items()},
        }


def test_neighbor_directory_matches_inventory_before_filter_and_pagination(admin_client, mixed_devices):
    c, ids = admin_client, mixed_devices["devices"]
    rows = c.get("/api/v1/inventory/topology-devices", params={"limit": 1}).json()
    assert rows["total"] == 2
    rows["items"] += c.get("/api/v1/inventory/topology-devices", params={"limit": 1, "offset": 1}).json()[
        "items"
    ]
    assert {r["id"] for r in rows["items"]} == {ids["inventory-core"], ids["inventory-server"]}
    assert {r["id"]: r["neighbor_count"] for r in rows["items"]} == {
        ids["inventory-core"]: 1,
        ids["inventory-server"]: 0,
    }
    assert c.get("/api/v1/inventory/topology-devices", params={"q": "ipam-server"}).json()["total"] == 0
    for path in ("/api/v1/links", "/api/v1/inventory/links"):
        data = c.get(path).json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == mixed_devices["links"]["valid"]
        assert c.get(path, params={"device_id": ids["ipam-server"]}).json()["total"] == 0
    filters = json.dumps(
        [
            {"field": "device_name", "op": "eq", "value": "ipam-server"},
            {"field": "remote_name", "op": "eq", "value": "ipam-server", "join": "or"},
        ]
    )
    assert c.get("/api/v1/inventory/links", params={"filters": filters}).json()["total"] == 0
    deleted = c.get("/api/v1/inventory/links", params={"deleted": True}).json()
    assert [r["id"] for r in deleted["items"]] == [mixed_devices["links"]["deleted-valid"]]


def test_connection_details_exclude_both_ipam_endpoints(admin_client, mixed_devices, env):
    ids = mixed_devices["devices"]
    for name in ("inventory-core", "inventory-server"):
        result = admin_client.get(f"/api/v1/devices/{ids[name]}/connections").json()
        assert len(result["items"]) == 1
        assert result["items"][0]["remote_device"]["id"] in {ids["inventory-core"], ids["inventory-server"]}
    assert admin_client.get(f"/api/v1/devices/{ids['ipam-server']}/connections").json()["items"] == []
    with env() as db:
        assert db.get(m.Device, ids["ipam-server"]) is not None


@pytest.mark.parametrize("name", ["incoming-ipam", "outgoing-ipam"])
def test_hidden_links_cannot_be_read_edited_or_deleted(admin_client, mixed_devices, name):
    id = mixed_devices["links"][name]
    assert admin_client.get(f"/api/v1/links/{id}").status_code == 404
    assert (
        admin_client.put(
            f"/api/v1/links/{id}/labels", json={"remote_name": "Other", "remote_port": "1"}
        ).status_code
        == 404
    )
    assert admin_client.delete(f"/api/v1/links/{id}").status_code == 404


def test_bulk_restore_rejects_mixed_inventory_ipam_selection_atomically(admin_client, mixed_devices, env):
    ids = [mixed_devices["links"][name] for name in ("deleted-valid", "deleted-ipam")]
    result = admin_client.post("/api/v1/inventory/links/bulk", json={"ids": ids, "action": "restore"})
    assert result.status_code == 404
    with env() as db:
        assert all(db.get(m.Link, id).auto_add_excluded for id in ids)


def test_manual_confirmation_does_not_bind_ipam_devices(mixed_devices, env):
    ids = mixed_devices["devices"]
    with env() as db:
        with pytest.raises(ValueError, match="envanter"):
            confirm_link(db, ids["inventory-core"], ids["ipam-server"])
        with pytest.raises(ValueError, match="envanter"):
            confirm_link(db, ids["ipam-server"], ids["inventory-core"])


def test_manual_peer_override_obeys_inventory_boundary(admin_client, mixed_devices, env):
    id = mixed_devices["links"]["valid"]
    with env() as db:
        link = db.get(m.Link, id)
        link.manual_remote_name = "ipam-server"
        link.manual_remote_device_id = mixed_devices["devices"]["ipam-server"]
        db.commit()
    assert admin_client.get("/api/v1/links").json()["total"] == 0
    assert admin_client.get("/api/v1/inventory/links").json()["total"] == 0
    assert admin_client.get(f"/api/v1/links/{id}").status_code == 404


def test_labels_do_not_resolve_ipam_identity(admin_client, mixed_devices):
    id = mixed_devices["links"]["valid"]
    result = admin_client.put(
        f"/api/v1/links/{id}/labels", json={"remote_name": "ipam-server", "remote_port": None}
    )
    assert result.status_code == 200, result.text
    assert result.json()["remote_device_id"] is None


def test_protocol_sync_never_collects_for_ipam_or_resolves_ipam_identity(mixed_devices, env):
    from netrix.discovery.links import sync_links

    ids = mixed_devices["devices"]
    data = {
        "neighbors": [
            {
                "interface_name": "new",
                "remote_name": "ipam-server",
                "remote_port": "eth0",
                "source": "lldp",
                "evidence": {"lldp": {"management_address": "192.0.2.3"}},
            }
        ]
    }
    with env() as db:
        sync_links(db, db.get(m.Device, ids["ipam-server"]), data)
        assert db.scalar(select(m.Link).where(m.Link.interface_name == "new")) is None
        sync_links(db, db.get(m.Device, ids["inventory-core"]), data)
        row = db.scalar(select(m.Link).where(m.Link.interface_name == "new"))
        assert row.remote_device_id is None and row.confidence == 0.5


def test_removing_inventory_membership_removes_existing_connections(admin_client, mixed_devices, env):
    with env() as db:
        db.get(m.Device, mixed_devices["devices"]["inventory-core"]).discovery_scope_id = None
        db.commit()
    assert admin_client.get("/api/v1/inventory/topology-devices").json()["total"] == 1
    assert admin_client.get("/api/v1/links").json()["total"] == 0
    assert admin_client.get("/api/v1/inventory/links", params={"deleted": True}).json()["total"] == 0
