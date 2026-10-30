import pytest
from netrix import models as m
from netrix.inventory.identity import apply_identity
from netrix.worker import claim, execute
from sqlalchemy import select
from test_identification import IdentityCollector, create_device


async def test_manual_edit_wins_even_when_collection_was_already_queued(admin_client, inventory, env):
    device, payload = create_device(admin_client, inventory)
    payload.update(vendor="Managed vendor", model="", kind="server")
    result = admin_client.put("/api/v1/devices/" + device["id"], json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["manual_identity_fields"] == ["kind", "model", "vendor"]
    claim()
    await execute(
        device["identification"]["job_id"],
        IdentityCollector({"vendor": "Cisco", "model": "C9300", "kind": "switch"}),
    )
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert (current["vendor"], current["model"], current["kind"]) == ("Managed vendor", "", "server")
    with env() as db:
        obs = db.scalar(select(m.Observation).where(m.Observation.device_id == device["id"]))
        assert obs.evidence["identity"] == {"vendor": "Cisco", "model": "C9300", "kind": "switch"}
        assert not db.scalar(select(m.Event).where(m.Event.kind == "device_identity_change"))


@pytest.mark.parametrize("protocol", ["snmpv2c", "snmpv3", "ssh", "rest"])
def test_only_edited_fields_are_protected_and_preference_survives_repeated_saves(
    admin_client, inventory, env, protocol
):
    device, payload = create_device(admin_client, inventory)
    payload["vendor"] = "Managed vendor"
    assert admin_client.put("/api/v1/devices/" + device["id"], json=payload).status_code == 200
    # Saving unchanged values and then changing an unrelated field never clears the preference.
    payload["name"] = "New managed name"
    assert admin_client.put("/api/v1/devices/" + device["id"], json=payload).status_code == 200
    with env() as db:
        row = db.get(m.Device, device["id"])
        assert row.manual_identity_fields == ["vendor"]
        apply_identity(
            db, row, {"vendor": "Observed vendor", "model": "C9300", "kind": "switch"}, None, protocol
        )
        db.commit()
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert (current["vendor"], current["model"], current["kind"], current["name"]) == (
        "Managed vendor",
        "C9300",
        "switch",
        "New managed name",
    )


def test_bulk_same_value_is_an_explicit_manual_choice(admin_client, inventory, env):
    device, payload = create_device(admin_client, inventory)
    response = admin_client.post(
        "/api/v1/inventory/devices/bulk",
        json={
            "ids": [device["id"]],
            "action": "update",
            "changes": {"vendor": payload["vendor"], "kind": payload["kind"]},
        },
    )
    assert response.status_code == 200, response.text
    with env() as db:
        row = db.get(m.Device, device["id"])
        assert row.manual_identity_fields == ["kind", "vendor"]
        apply_identity(db, row, {"vendor": "Cisco", "kind": "switch", "model": "C9300"}, None, "snmpv3")
        db.commit()
        assert (row.vendor, row.kind, row.model) == (payload["vendor"], payload["kind"], "C9300")


def test_unrelated_edit_does_not_lock_discovered_identity(admin_client, inventory):
    device, payload = create_device(admin_client, inventory)
    payload["name"] = "Renamed"
    result = admin_client.put("/api/v1/devices/" + device["id"], json=payload)
    assert result.status_code == 200
    assert result.json()["manual_identity_fields"] == []
    listing = admin_client.get("/api/v1/inventory/devices").json()
    assert "manual_identity_fields" not in {field["key"] for field in listing["columns"]}


@pytest.mark.parametrize("count", [1, 2])
def test_inventory_bulk_assign_replace_remove_backup_group(admin_client, inventory, env, count):
    c = admin_client
    devices = [create_device(c, inventory, management_ip=f"192.0.2.{i + 1}")[0] for i in range(count)]
    ids = [d["id"] for d in devices]
    groups = [
        c.post("/api/v1/backup-groups", json={"name": name}).json() for name in ["Switches", "Firewalls"]
    ]
    for value in [groups[0]["id"], groups[1]["id"], None]:
        result = c.post(
            "/api/v1/inventory/devices/bulk",
            json={"ids": ids, "action": "update", "changes": {"backup_group_id": value}},
        )
        assert result.status_code == 200, result.text
        for d in devices:
            current = c.get("/api/v1/devices/" + d["id"]).json()
            assert current["backup_group_id"] == value
            assert current["manual_identity_fields"] == []
            assert current["vendor"] == d["vendor"]
    result = c.post(
        "/api/v1/inventory/devices/bulk",
        json={
            "ids": ids,
            "action": "update",
            "changes": {"backup_group_id": "missing", "vendor": "must rollback"},
        },
    )
    assert result.status_code == 404
    for id in ids:
        current = c.get("/api/v1/devices/" + id).json()
        assert current["backup_group_id"] is None and current["vendor"] == "Manual vendor"
        assert current["manual_identity_fields"] == []
