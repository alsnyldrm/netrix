"""VLAN-scoped manual creation reads SQL only and rechecks vacancy on save."""

import pytest
from netrix import models as m
from netrix.ipam.service import observe
from sqlalchemy import func, select


@pytest.fixture
def allocation(admin_client, env):
    with env() as db:
        vrf = db.scalar(select(m.VRF))
        vlan = m.VLAN(name="Allocation", vid=20, cidr="192.0.2.0/29", vrf_id=vrf.id)
        db.add(vlan)
        db.flush()
        observe(db, vlan, "192.0.2.1", "icmp", vlan.id, {"reachability": "reachable"})
        inactive = observe(db, vlan, "192.0.2.2", "icmp", vlan.id, {"reachability": "no_reply"})
        db.add_all(
            [
                m.IPAddress(address="192.0.2.3", vlan_id=vlan.id, vrf_id=vrf.id, status="reserved"),
                m.IPAddress(
                    address="192.0.2.4", vlan_id=vlan.id, vrf_id=vrf.id, status="active", is_gateway=True
                ),
            ]
        )
        db.commit()
        return {"id": vlan.id, "vrf_id": vrf.id, "inactive_id": inactive.id}


def path(vlan, suffix="available-addresses"):
    return f"/api/v1/ipam/vlans/{vlan['id']}/{suffix}"


def test_vacant_choices_use_ping_and_exclude_reserved_gateway_and_network(admin_client, allocation, env):
    c, v = admin_client, allocation
    result = c.get(path(v) + "?limit=1").json()
    assert result == {"items": [{"address": "192.0.2.2"}], "next_offset": "3"}
    following = c.get(path(v) + "?offset=3").json()
    assert [r["address"] for r in following["items"]] == ["192.0.2.5", "192.0.2.6"]
    assert following["next_offset"] is None
    assert c.get(path(v) + "?q=192.0.2.6").json()["items"] == [{"address": "192.0.2.6"}]
    for address in ("192.0.2.0", "192.0.2.1", "192.0.2.3", "192.0.2.7", "198.51.100.1"):
        assert c.get(path(v), params={"q": address}).json()["items"] == []
    assert c.get(path(v) + "?offset=-1").status_code == 422
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0


@pytest.mark.parametrize("address", ["192.0.2.2", "192.0.2.5"])
def test_assign_creates_or_reuses_only_selected_ip_without_scanning(admin_client, allocation, env, address):
    v = allocation
    data = {
        "address": address,
        "vlan_id": v["id"],
        "vrf_id": v["vrf_id"],
        "hostname": "MANUAL-SERVER",
        "mac_address": "02-AA-BB-CC-DD-EE",
        "operating_system": "Linux",
    }
    result = admin_client.post(path(v, "addresses"), json=data)
    assert result.status_code == 201, result.text
    saved = result.json()
    assert saved["address"] == address and saved["mac_address"] == "02:aa:bb:cc:dd:ee"
    if address.endswith(".2"):
        assert saved["id"] == v["inactive_id"]
    with env() as db:
        assert (
            db.scalar(select(func.count()).select_from(m.IPAddress).where(m.IPAddress.address == address))
            == 1
        )
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert db.scalar(select(func.count()).select_from(m.VLAN)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.IPObservation)
                .where(m.IPObservation.address_id == v["inactive_id"])
            )
            == 1
        )
    assert admin_client.post(path(v, "addresses"), json=data).status_code == 409


def test_assignment_rechecks_live_sql_ping_and_rejects_wrong_scope(admin_client, allocation, env):
    v = allocation
    with env() as db:
        vlan = db.get(m.VLAN, v["id"])
        observe(db, vlan, "192.0.2.2", "icmp", vlan.id, {"reachability": "reachable"})
        db.commit()
    base = {"vlan_id": v["id"], "vrf_id": v["vrf_id"]}
    for address in ("192.0.2.1", "192.0.2.2", "192.0.2.3", "192.0.2.4"):
        assert admin_client.post(path(v, "addresses"), json={**base, "address": address}).status_code == 409
    for address in ("192.0.2.0", "192.0.2.7", "198.51.100.1"):
        assert admin_client.post(path(v, "addresses"), json={**base, "address": address}).status_code == 422
    assert (
        admin_client.post(
            path(v, "addresses"), json={**base, "address": "192.0.2.5", "vlan_id": "other"}
        ).status_code
        == 422
    )


def test_ipv6_exact_search_and_small_network_endpoints_are_bounded(admin_client, allocation, env):
    with env() as db:
        v = db.get(m.VLAN, allocation["id"])
        v.cidr = "2001:db8::/64"
        db.commit()
    result = admin_client.get(path(allocation) + "?limit=2").json()
    assert result["items"] == [{"address": "2001:db8::"}, {"address": "2001:db8::1"}]
    far = "2001:db8::ffff:fffe"
    assert admin_client.get(path(allocation), params={"q": far}).json()["items"] == [{"address": far}]
    with env() as db:
        db.get(m.VLAN, allocation["id"]).cidr = "198.51.100.0/31"
        db.commit()
    assert len(admin_client.get(path(allocation)).json()["items"]) == 2


def test_viewer_cannot_assign(admin_client, allocation, env):
    with env() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert admin_client.get(path(allocation)).status_code == 200
    assert (
        admin_client.post(
            path(allocation, "addresses"),
            json={
                "address": "192.0.2.5",
                "vrf_id": allocation["vrf_id"],
                "vlan_id": allocation["id"],
            },
        ).status_code
        == 403
    )
