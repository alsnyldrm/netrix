from datetime import timedelta

import pytest
from netrix import models as m
from netrix.configuration import baselines
from netrix.core import now
from netrix.identity.security import encrypt
from netrix.ipam import jobs
from sqlalchemy import select


def vlan(client, **extra):
    vrf = client.get("/api/v1/vrfs").json()["items"][0]["id"]
    response = client.post(
        "/api/v1/vlans", json={"name": "Servers", "vid": 20, "cidr": "192.0.2.0/30", "vrf_id": vrf, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def device(db, vrf, suffix="1"):
    d = m.Device(name="Device " + suffix, management_ip="192.0.2." + suffix, vrf_id=vrf)
    db.add(d)
    db.flush()
    return d


def snapshot(db, d, content, offset=0):
    j = m.Job(kind="backup", target_id=d.id, status="succeeded")
    db.add(j)
    db.flush()
    row = m.Snapshot(
        device_id=d.id,
        job_id=j.id,
        encrypted_content=encrypt(content),
        fingerprint=baselines.fingerprint(content),
        size_bytes=len(content),
        created_at=now() + timedelta(minutes=offset),
    )
    db.add(row)
    db.flush()
    return row


def test_vlan_owns_ipam_and_queues_without_scope_or_credentials(admin_client, env):
    row = vlan(admin_client)
    with env() as db:
        assert not list(db.scalars(select(m.Scope)))
        job = db.scalar(select(m.Job).where(m.Job.kind == "ipam_discover"))
        assert job.target_id == row["id"]
        assert not list(db.scalars(select(m.Device)))
    result = admin_client.get("/api/v1/ipam/vlans/" + row["id"] + "/addresses").json()
    assert result["total"] == "4" and len(result["items"]) == 4
    assert result["vlan"]["vid"] == 20
    assert admin_client.get("/api/v1/prefixes").status_code == 404
    assert admin_client.get("/api/v1/addresses").status_code == 404
    assert admin_client.get("/api/v1/ipam/addresses").status_code == 404


async def test_scan_dns_and_integration_do_not_create_inventory(admin_client, env, monkeypatch):
    row = vlan(admin_client)
    monkeypatch.setattr(jobs.adapters, "ping", async_value(True))
    monkeypatch.setattr(jobs.adapters, "reverse_dns", async_value("server.example"))
    with env() as db:
        job = db.scalar(select(m.Job).where(m.Job.kind == "ipam_discover"))
        job_id = job.id
    result = await jobs.scan(job_id)
    assert result["reachable"] == 2
    with env() as db:
        assert len(list(db.scalars(select(m.IPAddress)))) == 2
        assert not list(db.scalars(select(m.Device)))
    result = admin_client.get("/api/v1/ipam/vlans/" + row["id"] + "/addresses?active_only=true").json()
    assert all(r["hostname"] == "server.example" for r in result["items"])


def async_value(value):
    async def fn(*args):
        return value

    return fn


def test_integration_applies_to_all_vlans_without_block_permissions(admin_client, env):
    result = admin_client.post(
        "/api/v1/integrations",
        json={
            "name": "VMware",
            "kind": "vcenter",
            "host": "192.0.2.4",
            "port": 443,
            "username": "fixture",
            "password": "fixture-only",
            "enabled": True,
        },
    )
    assert result.status_code == 201, result.text
    assert "prefix_ids" not in result.json() and "vlan_ids" not in result.json()
    assert admin_client.post("/api/v1/integrations/" + result.json()["id"] + "/sync").status_code == 202


def test_inventory_accepts_only_its_own_discovered_devices(admin_client, inventory, env):
    with env() as db:
        a = device(db, inventory["vrf"]["id"])
        a.discovery_scope_id = inventory["scope"]["id"]
        device(db, inventory["vrf"]["id"], "2")
        db.commit()
        wanted = a.id
    result = admin_client.get("/api/v1/inventory/devices").json()
    assert [r["id"] for r in result["items"]] == [wanted]
    assert (
        admin_client.post(
            "/api/v1/devices",
            json={"name": "Manual", "management_ip": "198.51.100.3", "vrf_id": inventory["vrf"]["id"]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "before,after",
    [
        (
            "#config-version=FG-1\n#conf_file_ver=1\nconfig system global\n set hostname netrix\nend",
            "#config-version=FG-2\n#conf_file_ver=2\nconfig system global\n set hostname netrix\nend",
        ),
        ("!Version AOS-CX PL.10.17.1030\nhostname switch", "!Version AOS-CX PL.10.18.1000\nhostname switch"),
    ],
)
def test_export_versions_are_not_configuration_changes(before, after):
    assert baselines.fingerprint(before) == baselines.fingerprint(after)
    assert baselines.fingerprint(before) != baselines.fingerprint(
        after.replace("hostname", "hostname changed")
    )


def test_metadata_inside_quoted_values_is_significant():
    a = 'set banner "hello\n!Version AOS-CX PL.10.17.1030\n"'
    assert baselines.fingerprint(a) != baselines.fingerprint(a.replace("1030", "1040"))


def test_base_latest_approval_retention_and_secret_safe_compare(admin_client, env):
    row = vlan(admin_client)
    with env() as db:
        d = device(db, row["vrf_id"])
        d.backup_retention = 1
        first = snapshot(db, d, "hostname original\npassword first-secret", -3)
        second = snapshot(db, d, "hostname changed\npassword second-secret", -2)
        latest = snapshot(db, d, "hostname changed\npassword second-secret", -1)
        baselines.rebuild(db, d)
        db.commit()
        first_id, second_id, latest_id, did = first.id, second.id, latest.id, d.id
        assert d.base_snapshot_id == first.id and latest.changed
    pending = admin_client.get("/api/v1/inventory/snapshots?changed_only=true").json()
    assert [s["id"] for s in pending["items"]] == [latest_id]
    compare = admin_client.post("/api/v1/configuration/compare", json={"snapshot_ids": [first_id, latest_id]})
    assert compare.status_code == 200, compare.text
    assert "second-secret" not in compare.text and "first-secret" not in compare.text
    assert compare.json()["changed"] and any(l["changed"] for l in compare.json()["documents"][1]["lines"])
    assert admin_client.post("/api/v1/snapshots/" + second_id + "/approve").status_code == 409
    assert admin_client.post("/api/v1/snapshots/" + latest_id + "/approve").status_code == 200
    assert admin_client.get("/api/v1/inventory/snapshots?changed_only=true").json()["total"] == 0
    with env() as db:
        d = db.get(m.Device, did)
        new = snapshot(db, d, "hostname new-change", 0)
        baselines.rebuild(db, d)
        db.commit()
        new_id = new.id
    assert admin_client.get("/api/v1/dashboard").json()["counts"]["config_changes"] == 1
    assert admin_client.post("/api/v1/snapshots/" + new_id + "/base").status_code == 200
    assert admin_client.get("/api/v1/dashboard").json()["counts"]["config_changes"] == 0
    assert admin_client.delete("/api/v1/snapshots/" + new_id).status_code == 409
    with env() as db:
        from netrix.configuration.management import prune

        d = db.get(m.Device, did)
        d.base_snapshot_id = first_id
        prune(db, d)
        db.commit()
        assert db.get(m.Snapshot, first_id) is not None and db.get(m.Snapshot, new_id) is not None


def test_cross_device_compare_accepts_two_to_four_distinct_devices(admin_client, env):
    row = vlan(admin_client)
    with env() as db:
        ids = [snapshot(db, device(db, row["vrf_id"], str(n)), f"hostname device{n}").id for n in range(1, 5)]
        db.commit()
    result = admin_client.post(
        "/api/v1/configuration/compare", json={"snapshot_ids": ids, "distinct_devices": True}
    )
    assert result.status_code == 200 and len(result.json()["documents"]) == 4
    assert (
        admin_client.post("/api/v1/configuration/compare", json={"snapshot_ids": ids[:1]}).status_code == 422
    )
    assert (
        admin_client.post(
            "/api/v1/configuration/compare", json={"snapshot_ids": [ids[0], ids[0]]}
        ).status_code
        == 422
    )


def test_vlans_are_independent_of_inventory_scope_exclusions(admin_client, inventory, env):
    row = vlan(admin_client)
    with env() as db:
        scope = db.get(m.Scope, inventory["scope"]["id"])
        scope.enabled = False
        scope.exclusions = ["192.0.2.0/30"]
        db.commit()
        assert jobs.targets(db, db.get(m.VLAN, row["id"]), True) == ["192.0.2.1", "192.0.2.2"]
        db.delete(scope)
        db.commit()
        assert jobs.targets(db, db.get(m.VLAN, row["id"]), True) == ["192.0.2.1", "192.0.2.2"]


def test_normalized_fortios_comparisons_do_not_leak_multiline_secrets(admin_client, env):
    row = vlan(admin_client)
    with env() as db:
        d = device(db, row["vrf_id"])
        first = snapshot(
            db,
            d,
            '#config-version=FG-1\nconfig vpn certificate local\n edit "cert"\n set private-key "FIRST-SECRET\nCONTINUED-SECRET"\n next\nend',
            -1,
        )
        last = snapshot(
            db,
            d,
            '#config-version=FG-2\nconfig vpn certificate local\n edit "cert"\n set private-key "CHANGED-SECRET\nCONTINUED-SECRET"\n next\nend',
            0,
        )
        db.commit()
        ids = [first.id, last.id]
    result = admin_client.post("/api/v1/configuration/compare", json={"snapshot_ids": ids})
    assert result.status_code == 200, result.text
    for value in ("FIRST-SECRET", "CONTINUED-SECRET", "CHANGED-SECRET"):
        assert value not in result.text
    assert result.json()["changed"]


@pytest.mark.parametrize(
    "echo", ["show running-config\n", "switch# show running-config\n", "display current-configuration\n"]
)
def test_export_command_echo_is_not_a_config_change(echo):
    content = "Current configuration:\n!\nhostname switch\ninterface 1\n description original\n"
    assert baselines.fingerprint(content) == baselines.fingerprint(echo + content)
    assert baselines.fingerprint(content) != baselines.fingerprint(
        echo + content.replace("original", "changed")
    )


def test_export_command_inside_quoted_banner_is_still_significant():
    content = 'hostname switch\nbanner motd "hello\nshow running-config\n"'
    assert baselines.fingerprint(content) != baselines.fingerprint(
        content.replace("show running-config", "display current-configuration")
    )
