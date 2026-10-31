import pytest
from netrix import models as m
from netrix.worker import sync_interfaces
from sqlalchemy import select


@pytest.fixture
def device(env, inventory):
    with env() as db:
        row = m.Device(name="Ports", management_ip="192.0.2.1", vrf_id=inventory["vrf"]["id"])
        db.add(row)
        db.commit()
        return row.id


def observe(env, device_id, statuses, *, offset=0):
    with env() as db:
        device = db.scalar(select(m.Device).where(m.Device.id == device_id).with_for_update())
        job = m.Job(kind="discovery", target_id=device_id)
        db.add(job)
        db.flush()
        sync_interfaces(
            db,
            device,
            {
                "interfaces": [
                    {
                        "name": name,
                        "if_index": i + offset,
                        "oper_status": status,
                        "speed_bps": 1000000000,
                        "mac_address": "",
                        "description": "",
                        "counters": {
                            "in_octets": 100,
                            "out_octets": 200,
                            "uptime_ticks": 100,
                            "discontinuity_ticks": 0,
                        },
                    }
                    for i, (name, status) in enumerate(statuses.items(), 1)
                ]
            },
            job.id,
        )
        db.commit()
        return {
            p.name: {
                "id": p.id,
                "selected": p.is_managed,
                "excluded": p.auto_add_excluded,
                "deleted": p.is_deleted,
            }
            for p in db.scalars(select(m.Interface).where(m.Interface.device_id == device_id))
        }


def test_up_ports_adopted_and_down_unknown_wait_until_up(env, device):
    rows = observe(env, device, {"up": "up", "down": "down", "unknown": "unknown"})
    assert rows["up"]["selected"]
    assert not rows["down"]["selected"] and not rows["unknown"]["selected"]
    later = observe(env, device, {"up": "down", "down": "up", "unknown": "unknown"})
    assert later["up"]["selected"] and later["down"]["selected"]
    assert not later["unknown"]["selected"]


def test_explicit_exclusion_survives_cycles_and_ifindex_changes(admin_client, env, device):
    rows = observe(env, device, {"port1": "up", "port2": "down"})
    port1, port2 = rows["port1"]["id"], rows["port2"]["id"]
    result = admin_client.put(f"/api/v1/devices/{device}/interfaces", json={"exclude_ids": [port1]})
    assert result.status_code == 200 and result.json()["selected"] == 0
    rows = observe(env, device, {"port1": "down", "port2": "up"}, offset=10)
    assert not rows["port1"]["selected"] and rows["port1"]["excluded"]
    assert rows["port2"]["selected"] and not rows["port2"]["excluded"]
    rows = observe(env, device, {"port1": "up", "port2": "up"}, offset=20)
    assert rows["port1"]["id"] == port1 and not rows["port1"]["selected"]
    assert rows["port2"]["id"] == port2
    assert (
        admin_client.put(f"/api/v1/devices/{device}/interfaces", json={"include_ids": [port1]}).status_code
        == 200
    )
    rows = observe(env, device, {"port1": "down", "port2": "up"})
    assert rows["port1"]["selected"] and not rows["port1"]["excluded"]


def test_delta_save_does_not_remove_new_auto_selected_ports(admin_client, env, device):
    initial = observe(env, device, {"port1": "up", "port2": "down"})
    observe(env, device, {"port1": "up", "port2": "up", "new-port": "up"})
    result = admin_client.put(
        f"/api/v1/devices/{device}/interfaces", json={"exclude_ids": [initial["port1"]["id"]]}
    )
    assert result.status_code == 200 and result.json()["selected"] == 2
    with env() as db:
        assert db.scalar(select(m.Interface).where(m.Interface.name == "port2")).is_managed
        assert db.scalar(select(m.Interface).where(m.Interface.name == "new-port")).is_managed


def test_delete_excludes_and_removed_actions_are_rejected(admin_client, env, device):
    rows = observe(env, device, {"deleted": "up", "disabled": "up"})
    deleted, disabled = rows["deleted"]["id"], rows["disabled"]["id"]
    assert (
        admin_client.post(
            "/api/v1/inventory/interfaces/bulk", json={"ids": [deleted], "action": "delete"}
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            "/api/v1/inventory/interfaces/bulk", json={"ids": [disabled], "action": "disable"}
        ).status_code
        == 422
    )
    rows = observe(env, device, {"deleted": "up", "disabled": "up"})
    assert rows["deleted"]["excluded"] and rows["deleted"]["deleted"] and not rows["deleted"]["selected"]
    assert rows["disabled"]["selected"]
    assert (
        admin_client.put(f"/api/v1/devices/{device}/interfaces", json={"include_ids": [deleted]}).status_code
        == 200
    )
    rows = observe(env, device, {"deleted": "up", "disabled": "down"})
    assert rows["deleted"]["selected"] and not rows["deleted"]["excluded"] and not rows["deleted"]["deleted"]


def test_legacy_full_selection_is_preserved(admin_client, env, device):
    rows = observe(env, device, {"port1": "up", "port2": "down"})
    assert (
        admin_client.put(
            f"/api/v1/devices/{device}/interfaces", json={"ids": [rows["port1"]["id"]]}
        ).status_code
        == 200
    )
    rows = observe(env, device, {"port1": "up", "port2": "up"})
    assert not rows["port2"]["selected"] and rows["port2"]["excluded"]


def test_selection_atomic_validation_and_viewer_guard(admin_client, env, device):
    rows = observe(env, device, {"port1": "up"})
    port = rows["port1"]["id"]
    for payload in (
        {"include_ids": [port], "exclude_ids": [port]},
        {"ids": [port], "exclude_ids": ["missing"]},
        {"exclude_ids": [port, "missing"]},
    ):
        assert admin_client.put(f"/api/v1/devices/{device}/interfaces", json=payload).status_code == 422
        with env() as db:
            assert db.get(m.Interface, port).is_managed and not db.get(m.Interface, port).auto_add_excluded
    with env() as db:
        db.scalar(select(m.User).where(m.User.email == "owner@example.test")).role = "viewer"
        db.commit()
    assert (
        admin_client.put(f"/api/v1/devices/{device}/interfaces", json={"exclude_ids": [port]}).status_code
        == 403
    )
