"""Device-oriented topology projections, without real network calls."""

import pytest
from conftest import make_inventory_scope
from netrix import models as m
from netrix.core import now
from netrix.discovery.device_connections import device_connections
from sqlalchemy import select


@pytest.fixture
def network(env):
    with env() as db:
        vrf, other = m.VRF(name="main"), m.VRF(name="other")
        db.add_all([vrf, other, m.DeviceType(code="custom-core", name="Backbone")])
        db.flush()
        scope = make_inventory_scope(db, vrf.id)
        devices = {}
        for i, (name, kind) in enumerate(
            [
                ("gateway", "firewall"),
                ("core", "custom-core"),
                ("edge", "switch"),
                ("leaf", "switch"),
                ("isolated-a", "switch"),
                ("isolated-b", "switch"),
            ]
        ):
            d = m.Device(
                name=name,
                kind=kind,
                management_ip=f"192.0.2.{i + 1}",
                vrf_id=vrf.id,
                discovery_scope_id=scope.id,
            )
            db.add(d)
            db.flush()
            devices[name] = d.id
        db.commit()
    return env, devices


def add_link(db, ids, local, remote, a="1", b="2", **kwargs):
    link = m.Link(
        device_id=ids[local],
        remote_device_id=ids[remote] if remote in ids else None,
        remote_name=remote,
        interface_name=a,
        remote_port=b,
        source=kwargs.pop("source", "lldp"),
        confidence=kwargs.pop("confidence", 0.65),
        last_seen_at=now(),
        **kwargs,
    )
    db.add(link)
    db.flush()
    return link


def read(db, ids, name="edge"):
    return device_connections(db, db.get(m.Device, ids[name]))["items"]


def test_reverse_observation_and_reciprocal_dedup_keep_parallel_ports(network):
    sf, ids = network
    with sf() as db:
        add_link(db, ids, "core", "edge", "F2", "49")
        add_link(db, ids, "edge", "core", "49", "F2", source="cdp")
        add_link(db, ids, "core", "edge", "F3", "50")
        rows = read(db, ids)
        assert len(rows) == 2
        assert [(r["local_port"], r["remote_port"]) for r in rows] == [("49", "F2"), ("50", "F3")]
        assert rows[0]["remote_device"]["id"] == ids["core"]
        assert rows[0]["sources"] == ["cdp", "lldp"]
        assert rows[0]["confidence"] == 0.65
        assert all(r["direction"] == "upstream" and r["last_seen_at"] for r in rows)


def test_hierarchy_infers_upper_and_lower_connections_with_cycles(network):
    sf, ids = network
    with sf() as db:
        add_link(db, ids, "gateway", "core")
        add_link(db, ids, "core", "edge")
        add_link(db, ids, "edge", "leaf")
        add_link(db, ids, "core", "leaf")
        add_link(db, ids, "edge", "gateway", "3", "4")
        assert {r["remote_name"]: r["direction"] for r in read(db, ids)} == {
            "gateway": "upstream",
            "core": "peer",
            "leaf": "downstream",
        }
        assert all(r["direction"] == "downstream" for r in read(db, ids, "gateway"))


def test_disconnected_component_does_not_invent_an_alphabetical_root(network):
    sf, ids = network
    with sf() as db:
        add_link(db, ids, "isolated-a", "isolated-b")
        assert read(db, ids, "isolated-b")[0]["direction"] == "unknown"


def test_unresolved_and_manual_unknown_ports_remain_honest(network):
    sf, ids = network
    with sf() as db:
        add_link(db, ids, "edge", "unmanaged", "9", "", confidence=0.5)
        add_link(db, ids, "edge", "core", "", "", source="manual", confidence=1)
        rows = read(db, ids)
        assert rows[0]["direction"] == "upstream"
        assert rows[0]["local_port"] is rows[0]["remote_port"] is None
        assert rows[1]["remote_device"] is None
        assert rows[1]["remote_name"] == "unmanaged"
        assert rows[1]["direction"] == "unknown"


def test_archived_retired_cross_vrf_and_self_links_are_not_shown(network):
    sf, ids = network
    with sf() as db:
        add_link(db, ids, "core", "edge", is_current=False)
        add_link(db, ids, "gateway", "edge")
        db.get(m.Device, ids["gateway"]).archived = True
        add_link(db, ids, "edge", "leaf")
        db.get(m.Device, ids["leaf"]).archived = True
        add_link(db, ids, "edge", "edge")
        add_link(db, ids, "isolated-a", "edge")
        db.get(m.Device, ids["isolated-a"]).vrf_id = db.scalar(select(m.VRF.id).where(m.VRF.name == "other"))
        db.flush()
        assert read(db, ids) == []


def test_endpoint_requires_login_and_supports_viewers(network, client, admin_client):
    sf, ids = network
    with sf() as db:
        add_link(db, ids, "core", "edge", "F2", "49")
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    response = admin_client.get(f"/api/v1/devices/{ids['edge']}/connections")
    assert response.status_code == 200
    assert response.json()["items"][0]["remote_port"] == "F2"
    assert "evidence" not in response.text and "credential" not in response.text
    assert admin_client.get("/api/v1/devices/missing/connections").status_code == 404
    client.cookies.clear()
    assert client.get(f"/api/v1/devices/{ids['edge']}/connections").status_code == 401


def test_stp_root_trunk_groups_members_and_excludes_non_root_neighbors(network):
    sf, ids = network
    with sf() as db:
        db.get(m.Device, ids["edge"]).kind = "custom-core"
        for local, remote in [("A1", "I4"), ("B1", "D2")]:
            add_link(
                db,
                ids,
                "edge",
                "core",
                local,
                remote,
                evidence={
                    "local_aggregate": {"name": "Trk1", "type": "LACP"},
                    "spanning_tree": {"port": "Trk1", "is_root": False},
                },
            )
        add_link(db, ids, "edge", "leaf", "A2", "48")
        rows = read(db, ids)
        upper = [r for r in rows if r["direction"] == "upstream"]
        assert len(upper) == 1
        assert upper[0]["direction_basis"] == "stp"
        assert upper[0]["local_aggregate"]["name"] == "Trk1"
        assert upper[0]["members"] == [
            {"local_port": "A1", "remote_port": "I4"},
            {"local_port": "B1", "remote_port": "D2"},
        ]
        assert rows[1]["direction"] != "upstream"


def test_core_behind_core_uses_distance_to_firewall_not_equal_backbone_tier(network):
    sf, ids = network
    with sf() as db:
        db.get(m.Device, ids["edge"]).kind = "custom-core"
        add_link(db, ids, "gateway", "core")
        add_link(db, ids, "core", "edge")
        assert read(db, ids)[0]["direction"] == "upstream"
