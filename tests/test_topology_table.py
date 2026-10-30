import json

import pytest
from netrix import models as m


@pytest.fixture
def links(env, admin_client):
    with env() as db:
        vrf = m.VRF(name="Topology test")
        site = m.Site(name="Merkez", code="T")
        db.add_all([vrf, site])
        db.flush()
        devices = [
            m.Device(
                name=name,
                management_ip=f"192.0.2.{i + 1}",
                kind="switch",
                vendor="Aruba",
                model="2930F",
                vrf_id=vrf.id,
                site_id=site.id,
                archived=i == 2,
            )
            for i, name in enumerate(["Core A", "Core B", "Archived"])
        ]
        db.add_all(devices)
        db.flush()
        db.add_all(
            [
                m.Link(
                    device_id=devices[0].id,
                    interface_name="H3",
                    remote_name="Edge A",
                    remote_port="49",
                    source="lldp+cdp",
                    confidence=0.5,
                    remote_device_id=devices[1].id,
                ),
                m.Link(
                    device_id=devices[0].id,
                    interface_name="H4",
                    remote_name="Edge B",
                    remote_port="50",
                    source="manual",
                    confidence=1,
                ),
                m.Link(
                    device_id=devices[0].id,
                    interface_name="H99",
                    remote_name="Obsolete",
                    remote_port="1",
                    source="lldp",
                    is_current=False,
                ),
                m.Link(
                    device_id=devices[2].id,
                    interface_name="H3",
                    remote_name="Hidden",
                    remote_port="1",
                    source="lldp",
                ),
                *[
                    m.Link(
                        device_id=devices[1].id,
                        interface_name=f"G{i}",
                        remote_name=f"Peer {i}",
                        remote_port="49",
                        source="cdp",
                        confidence=0.65,
                    )
                    for i in range(30)
                ],
            ]
        )
        db.commit()


def query(client, rules, **kwargs):
    return client.get("/api/v1/inventory/links", params={"filters": json.dumps(rules), **kwargs})


def test_topology_filters_apply_left_to_right_before_pagination(admin_client, links):
    rules = [
        {"field": "device_name", "op": "eq", "value": "Core A"},
        {"field": "management_ip", "op": "eq", "value": "192.0.2.2", "join": "or"},
        {"field": "interface_name", "op": "eq", "value": "H3", "join": "and"},
    ]
    result = query(admin_client, rules).json()
    assert result["total"] == 1 and result["items"][0]["remote_name"] == "Edge A"
    result = query(admin_client, rules[:2], limit=25, offset=25).json()
    assert result["total"] == 32 and len(result["items"]) == 7
    assert all(row["is_current"] for row in result["items"])
    row = query(admin_client, rules).json()["items"][0]
    assert row["remote_device_name"] == "Core B" and row["remote_management_ip"] == "192.0.2.2"
    assert row["device_kind_name"] and row["vendor"] == "Aruba" and row["site_name"] == "Merkez"
    assert row["confidence_percent"] == 50


@pytest.mark.parametrize(
    ("field", "op", "value", "total"),
    [
        ("confidence_percent", "gt", "90", 1),
        ("source", "eq", "Kullanıcı doğrulaması", 1),
        ("source", "eq", "LLDP + CDP", 1),
        ("source", "contains", "LLDP + CDP", 1),
        ("device_kind", "eq", "Switch", 32),
        ("model", "contains", "2930", 32),
        ("remote_name", "contains", "Peer 29", 1),
    ],
)
def test_topology_device_fields_and_display_values(admin_client, links, field, op, value, total):
    response = query(admin_client, [{"field": field, "op": op, "value": value}])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == total


def test_topology_query_metadata_search_and_validation(admin_client, links, env):
    data = query(admin_client, [], q="Peer 29").json()
    assert data["total"] == 1
    columns = {c["key"]: c["label"] for c in data["columns"]}
    assert columns["device_name"] == "Kaynak cihaz" and columns["confidence_percent"] == "Güven (%)"
    assert not {"evidence", "is_current", "encrypted_secret", "password_hash"} & columns.keys()
    assert query(admin_client, [], q="%").json()["total"] == 0
    for rules in [
        [{"field": "evidence", "op": "contains", "value": "x"}],
        [{"field": "device_name", "op": "gt", "value": "3"}],
        [{"field": "device_name", "op": "eq", "value": "x"}] * 21,
    ]:
        assert query(admin_client, rules).status_code == 422
    # Read-only users can customize their own view too.
    from sqlalchemy import select

    with env() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert query(admin_client, []).status_code == 200


def test_topology_directory_counts_current_records_and_scopes_by_id(admin_client, links, env):
    from sqlalchemy import select

    with env() as db:
        source = db.scalar(select(m.Device).where(m.Device.name == "Core A"))
        db.add(m.Device(name="Core A", management_ip="192.0.2.99", vrf_id=source.vrf_id))
        db.commit()
    directory = admin_client.get("/api/v1/inventory/topology-devices").json()
    assert directory["total"] == 3
    rows = {r["management_ip"]: r for r in directory["items"]}
    assert rows["192.0.2.1"]["neighbor_count"] == 2
    assert rows["192.0.2.2"]["neighbor_count"] == 30
    assert rows["192.0.2.99"]["neighbor_count"] == 0
    assert rows["192.0.2.99"]["latest_neighbor_at"] is None
    for ip, total in [("192.0.2.1", 2), ("192.0.2.2", 30), ("192.0.2.99", 0)]:
        data = query(
            admin_client,
            [
                {"field": "remote_name", "op": "not_contains", "value": "absent"},
                {"field": "device_name", "op": "contains", "value": "Core", "join": "or"},
            ],
            device_id=rows[ip]["id"],
            offset=25,
        ).json()
        assert data["total"] == total
        assert all(row["device_id"] == rows[ip]["id"] for row in data["items"])
    result = admin_client.get(
        "/api/v1/inventory/topology-devices",
        params={"filters": json.dumps([{"field": "neighbor_count", "op": "gt", "value": "2"}]), "limit": 1},
    ).json()
    assert result["total"] == 1 and result["items"][0]["name"] == "Core B"


@pytest.mark.parametrize(
    ("field", "value", "total"),
    [
        ("source", "LLDP + CDP", 31),
        ("source", "Kullanıcı", 31),
        ("remote_device_name", "Core B", 31),
        ("remote_name", "%", 32),
        ("remote_name", "_", 32),
        ("remote_name", "!", 32),
        ("device_kind", "Switch", 0),
        ("remote_name", "PEER", 2),
    ],
)
def test_not_contains_localized_null_and_literal_values(admin_client, links, field, value, total):
    response = query(admin_client, [{"field": field, "op": "not_contains", "value": value}], limit=1)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == total
    assert len(response.json()["items"]) == min(1, total)
