import json

import pytest
from netrix import models as m
from netrix.core import now
from netrix.discovery.device_connections import device_connections
from netrix.discovery.links import sync_links
from netrix.services import serialize
from sqlalchemy import select


@pytest.fixture
def link_record(env, admin_client):
    with env() as db:
        vrf = m.VRF(name="Edit labels")
        db.add(vrf)
        db.flush()
        source = m.Device(name="Core", management_ip="192.0.2.1", vrf_id=vrf.id)
        old = m.Device(name="Old", management_ip="192.0.2.2", vrf_id=vrf.id)
        new = m.Device(name="New", management_ip="192.0.2.3", vrf_id=vrf.id)
        db.add_all([source, old, new])
        db.flush()
        link = m.Link(
            device_id=source.id,
            interface_name="A2",
            remote_name="Old",
            remote_port="NIC",
            remote_device_id=old.id,
            source="lldp+cdp",
            confidence=0.9,
            last_seen_at=now(),
            evidence={"lldp": {"system_name": "Old", "chassis_id": "38:21:c7:3c:b2:40", "port_id": "NIC"}},
        )
        db.add(link)
        db.commit()
        return {
            "id": link.id,
            "source": source.id,
            "old": old.id,
            "new": new.id,
            "vrf": vrf.id,
            "observed": link.last_seen_at,
        }


def save(client, record, name="New", port="49"):
    return client.put(f"/api/v1/links/{record['id']}/labels", json={"remote_name": name, "remote_port": port})


def test_edit_preserves_observation_updates_views_and_survives_discovery(admin_client, link_record, env):
    result = save(admin_client, link_record)
    assert result.status_code == 200, result.text
    row = result.json()
    assert row["remote_name"] == "New" and row["remote_port"] == "49"
    assert row["remote_device_id"] == link_record["new"] and row["confidence"] == 0.65
    assert row["source"] == "lldp+cdp" and row["has_manual_changes"]
    assert row["observed_remote_name"] == "Old" and row["observed_remote_port"] == "NIC"
    with env() as db:
        link = db.get(m.Link, link_record["id"])
        assert (
            link.remote_name == "Old"
            and link.remote_port == "NIC"
            and link.remote_device_id == link_record["old"]
        )
        assert link.last_seen_at == link_record["observed"]
        assert db.scalar(select(m.Audit).where(m.Audit.action == "edit_link_labels"))
        event = db.scalar(select(m.Event).where(m.Event.kind == "link_labels_edited"))
        assert event.details["after"] == {"remote_name": "New", "remote_port": "49"}
        source = db.get(m.Device, link_record["source"])
        # Same physical neighbor with a changed advertised label and port alias.
        sync_links(
            db,
            source,
            {
                "neighbors": [
                    {
                        "interface_name": "A2",
                        "remote_name": "Old renamed",
                        "remote_port": "NIC-new",
                        "source": "lldp+cdp",
                        "evidence": link.evidence,
                    }
                ],
                "neighbor_protocols_complete": ["lldp", "cdp"],
            },
        )
        db.commit()
        db.refresh(link)
        assert link.is_current and link.remote_name == "Old renamed"
        assert serialize(link)["remote_name"] == "New" and serialize(link)["remote_port"] == "49"
        outgoing = device_connections(db, source)["items"]
        assert len(outgoing) == 1 and outgoing[0]["remote_device"]["id"] == link_record["new"]
        assert outgoing[0]["remote_port"] == "49"
        incoming = device_connections(db, db.get(m.Device, link_record["new"]))["items"]
        assert len(incoming) == 1 and incoming[0]["local_port"] == "49"
        assert device_connections(db, db.get(m.Device, link_record["old"]))["items"] == []
    for field, value in [("remote_name", "New"), ("remote_port", "49"), ("remote_device_name", "New")]:
        response = admin_client.get(
            "/api/v1/inventory/links",
            params={"filters": json.dumps([{"field": field, "op": "eq", "value": value}])},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
    assert admin_client.get("/api/v1/inventory/links", params={"q": "Old renamed"}).json()["total"] == 0
    reset = save(admin_client, link_record, None, None).json()
    assert reset["remote_name"] == "Old renamed" and not reset["has_manual_changes"]


def test_port_only_empty_port_and_unresolved_name(admin_client, link_record):
    row = save(admin_client, link_record, None, "").json()
    assert row["remote_port"] == "" and row["remote_device_id"] == link_record["old"]
    assert row["confidence"] == 0.9 and row["has_manual_changes"]
    row = save(admin_client, link_record, "Unknown neighbor", "uplink-2").json()
    assert row["remote_device_id"] is None and row["confidence"] == 0.65
    data = admin_client.get("/api/v1/inventory/links").json()["items"][0]
    assert data["remote_device_name"] is None and data["confidence_percent"] == 65
    row = save(admin_client, link_record, None, None).json()
    assert row["remote_port"] == "NIC" and row["remote_device_id"] == link_record["old"]


@pytest.mark.parametrize(
    "name,port",
    [("", "1"), ("  ", "1"), ("a" * 191, "1"), ("ok", "p" * 121), ("a\x00b", "1"), ("ok", "a\nb")],
)
def test_invalid_labels_rejected(admin_client, link_record, name, port):
    assert save(admin_client, link_record, name, port).status_code == 422


def test_role_and_current_record_guards(admin_client, link_record, env):
    assert (
        admin_client.put(
            f"/api/v1/links/{link_record['id']}/labels",
            json={"remote_name": "New", "remote_port": "49", "source": "manual"},
        ).status_code
        == 422
    )
    assert save(admin_client, {"id": "missing"}).status_code == 404
    with env() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert save(admin_client, link_record).status_code == 403
    with env() as db:
        db.scalar(select(m.User)).role = "operator"
        db.commit()
    assert save(admin_client, link_record).status_code == 200
    with env() as db:
        db.get(m.Link, link_record["id"]).is_current = False
        db.commit()
    assert save(admin_client, link_record).status_code == 409
    with env() as db:
        db.get(m.Link, link_record["id"]).is_current = True
        db.get(m.Device, link_record["source"]).archived = True
        db.commit()
    assert save(admin_client, link_record).status_code == 409


def test_duplicate_or_cross_vrf_name_is_not_a_device_match(admin_client, link_record, env):
    with env() as db:
        db.add(m.Device(name="New", management_ip="192.0.2.4", vrf_id=link_record["vrf"]))
        other = m.VRF(name="Other")
        db.add(other)
        db.flush()
        db.add(m.Device(name="Outside", management_ip="192.0.2.5", vrf_id=other.id))
        db.commit()
    for name in ("New", "Outside", "Core"):
        row = save(admin_client, link_record, name).json()
        assert row["remote_name"] == name and row["remote_device_id"] is None


def test_protocol_merge_preserves_the_operator_edited_record(admin_client, link_record, env):
    save(admin_client, link_record, "Manual name", "49")
    with env() as db:
        link = db.get(m.Link, link_record["id"])
        link.source = "lldp"
        duplicate = m.Link(
            device_id=link.device_id,
            interface_name="A2",
            remote_name="38:21:c7:3c:b2:40",
            remote_port="NIC",
            source="cdp",
            evidence={"cdp": {"device_id": "38:21:c7:3c:b2:40", "port_id": "NIC"}},
        )
        db.add(duplicate)
        db.flush()
        sync_links(
            db,
            db.get(m.Device, link.device_id),
            {
                "neighbors": [
                    {
                        "interface_name": "A2",
                        "remote_name": "Combined",
                        "remote_port": "NIC",
                        "source": "lldp+cdp",
                        "evidence": link.evidence,
                    }
                ],
                "neighbor_protocols_complete": ["lldp", "cdp"],
            },
        )
        db.commit()
        assert link.is_current and not duplicate.is_current
        assert serialize(link)["remote_name"] == "Manual name" and serialize(link)["remote_port"] == "49"
