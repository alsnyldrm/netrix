"""Blacklist drafts use managed inventory and never enqueue network writes."""

import pytest
from netrix import models as m
from sqlalchemy import func, select

ROOT = "/api/v1/blacklist"


@pytest.fixture
def devices(admin_client, env):
    with env() as db:
        vrf = db.scalar(select(m.VRF))
        if not vrf:
            vrf = m.VRF(name="Blacklist fixture")
            db.add(vrf)
            db.flush()
        specs = [
            ("5412", "J9851A", "aruba_5400", {}),
            ("5406", "J9850A", "aruba_5400", {}),
            ("2930", "JL256A", "aruba_2900", {}),
            ("6100", "JL675A", "aruba_6100", {}),
            ("7205", "Aruba 7205", "aruba_7200", {}),
            ("1950", "JG963A", "hp_1950", {}),
            ("Firewall", "JL256A", "aruba_2900", {"kind": "firewall"}),
            ("Gateway", "JL256A", "aruba_2900", {"is_gateway": True}),
            ("Archived", "JL256A", "aruba_2900", {"archived": True}),
            ("Retired", "JL256A", "aruba_2900", {"lifecycle_status": "retired"}),
            ("2920", "J9726A", "aruba_2900", {}),
            ("7210", "Aruba 7210", "aruba_7200", {}),
            ("Unknown", "", "aruba_6100", {}),
        ]
        result = {}
        for number, (name, model, adapter, overrides) in enumerate(specs):
            values = dict(
                name=name,
                model=model,
                adapter=adapter,
                vrf_id=vrf.id,
                management_ip=f"192.0.2.{number + 1}",
                kind="switch",
            )
            values.update(overrides)
            device = m.Device(**values)
            db.add(device)
            db.flush()
            result[name] = device.id
        db.commit()
        return result


def group_payload(device_id, name="Campus", acl="BLOCKED_IPS"):
    return {
        "name": name,
        "device_ids": [device_id],
        "profiles": {"aos_switch": {"type": "extended", "name": acl}},
    }


def create_group(client, payload):
    response = client.post(ROOT + "/groups", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_inventory_only_contains_requested_active_models(admin_client, devices):
    response = admin_client.get(ROOT + "/devices")
    assert response.status_code == 200
    assert {row["name"] for row in response.json()["items"]} == {
        "5412",
        "5406",
        "2930",
        "6100",
        "7205",
        "1950",
    }


@pytest.mark.parametrize("name", ["Firewall", "Gateway", "Archived", "Retired", "2920", "7210", "Unknown"])
def test_ineligible_devices_cannot_be_submitted_directly(admin_client, devices, name):
    response = admin_client.post(ROOT + "/groups", json=group_payload(devices[name]))
    assert response.status_code == 422
    assert admin_client.get(ROOT + "/groups").json()["items"] == []


def test_multigroup_preview_deduplicates_shared_acl_and_remains_passive(admin_client, devices, env):
    first = create_group(admin_client, group_payload(devices["2930"], "Campus"))
    second = create_group(admin_client, group_payload(devices["2930"], "Remote"))
    response = admin_client.post(
        ROOT + "/entries",
        json={
            "address": "192.0.2.100",
            "description": "Fixture",
            "group_ids": [first["id"], second["id"], first["id"]],
        },
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    preview = admin_client.get(ROOT + f"/entries/{entry['id']}/preview")
    assert preview.status_code == 200, preview.text
    targets = preview.json()["targets"]
    assert len(targets) == 1
    assert set(targets[0]["group_ids"]) == {first["id"], second["id"]}
    assert targets[0]["profile"]["name"] == "BLOCKED_IPS"
    assert targets[0]["issue"] == ""
    # A different ACL on the same device remains a separate target.
    changed = admin_client.patch(
        ROOT + f"/groups/{second['id']}",
        json=group_payload(devices["2930"], "Remote", "OTHER_ACL"),
    )
    assert changed.status_code == 200
    assert len(admin_client.get(ROOT + f"/entries/{entry['id']}/preview").json()["targets"]) == 2
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert db.scalar(select(func.count()).select_from(m.BlacklistEntryGroup)) == 2


def test_preview_revalidates_device_after_group_saved(admin_client, devices, env):
    group = create_group(admin_client, group_payload(devices["5412"]))
    entry = admin_client.post(
        ROOT + "/entries",
        json={
            "address": "192.0.2.100",
            "group_ids": [group["id"]],
        },
    ).json()
    with env() as db:
        db.get(m.Device, devices["5412"]).is_gateway = True
        db.commit()
    target = admin_client.get(ROOT + f"/entries/{entry['id']}/preview").json()["targets"][0]
    assert target["issue"]
    assert target["profile"] is None


@pytest.mark.parametrize(
    "profile",
    [
        {"type": "session", "name": "block"},
        {"type": "extended", "number": 99},
        {"type": "standard", "number": 100},
        {"type": "extended", "name": "block\nwrite memory"},
        {"type": "extended", "name": "block", "number": 100},
        {"type": "extended", "number": True},
    ],
)
def test_invalid_acl_profile_cannot_be_saved(admin_client, devices, profile):
    payload = group_payload(devices["2930"])
    payload["profiles"]["aos_switch"] = profile
    assert admin_client.post(ROOT + "/groups", json=payload).status_code == 422


def test_ipv6_canonicalization_duplicate_and_invalid_ip(admin_client, devices):
    group = create_group(admin_client, group_payload(devices["2930"]))
    payload = {"address": "2001:0db8:0000::1", "group_ids": [group["id"]]}
    response = admin_client.post(ROOT + "/entries", json=payload)
    assert response.status_code == 201
    entry = response.json()
    assert entry["address"] == "2001:db8::1"
    assert admin_client.post(ROOT + "/entries", json={**payload, "address": "2001:db8::1"}).status_code == 409
    preview = admin_client.get(ROOT + f"/entries/{entry['id']}/preview").json()
    assert "IPv6" in preview["targets"][0]["issue"]
    for address in ("192.0.2.0/24", "invalid", "192.0.2.999", "fe80::1%eth0"):
        assert admin_client.post(ROOT + "/entries", json={**payload, "address": address}).status_code == 422


def test_roles_and_anonymous_access(admin_client, devices, env):
    group = create_group(admin_client, group_payload(devices["2930"]))
    payload = {"address": "192.0.2.100", "group_ids": [group["id"]]}
    with env() as db:
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    assert admin_client.get(ROOT + "/entries").status_code == 200
    assert admin_client.post(ROOT + "/entries", json=payload).status_code == 403
    assert (
        admin_client.post(ROOT + "/groups", json=group_payload(devices["2930"], "Other")).status_code == 403
    )
    with env() as db:
        db.scalar(select(m.User)).role = "operator"
        db.commit()
    assert admin_client.post(ROOT + "/entries", json=payload).status_code == 201
    assert (
        admin_client.post(ROOT + "/groups", json=group_payload(devices["2930"], "Other")).status_code == 403
    )
    admin_client.cookies.clear()
    assert admin_client.get(ROOT + "/entries").status_code == 401


def test_invalid_group_references_and_missing_family_do_not_partially_save(admin_client, devices, env):
    payload = group_payload(devices["2930"])
    payload["device_ids"].append(devices["6100"])
    assert admin_client.post(ROOT + "/groups", json=payload).status_code == 422
    assert (
        admin_client.post(
            ROOT + "/entries",
            json={
                "address": "192.0.2.100",
                "group_ids": ["missing"],
            },
        ).status_code
        == 422
    )
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.BlacklistEntry)) == 0
        assert db.scalar(select(func.count()).select_from(m.ACLGroup)) == 0
