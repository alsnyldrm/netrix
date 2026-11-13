"""Front/rear cabling, reciprocal updates and eventual matching without inventory writes."""

from unittest.mock import Mock

from netrix import models as m
from netrix.ipam import patch_links
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from test_patch_panels import rack as rack


def panel(c, cabinet, *, name="FIBER-01", count=2):
    root = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    response = c.post(root, json=dict(name=name, kind="fiber", start_unit=2, port_count=count))
    assert response.status_code == 201, response.text
    row = response.json()
    url = root + "/" + row["id"]
    return url, c.get(url + "/ports").json()["items"]


def target(cabinet, devices):
    return dict(
        site_id=cabinet["site_id"],
        floor_number="L-1",
        department_name="A",
        room_name="Elektrik Odası",
        cabinet_name="01",
        panel_name="FIBER-01",
        panel_unit=2,
        port_number="1",
        device_id=devices[1][0],
        interface_id=devices[1][1],
    )


def remote(c, cabinet, institution, *, name="Elektrik Odası"):
    room = c.post(
        "/api/v1/sites",
        json=dict(
            name=name,
            parent_id=cabinet["site_id"],
            institution_id=institution["id"],
            floor_number="L-1",
            department_name="A",
        ),
    )
    assert room.status_code == 201, room.text
    result = c.post(
        "/api/v1/cabinets",
        json=dict(name="01", site_id=cabinet["site_id"], sub_site_id=room.json()["id"], units=12),
    )
    assert result.status_code == 201, result.text
    return room.json(), result.json()


def row(c, url, position=0):
    response = c.get(url + "/ports")
    assert response.status_code == 200, response.text
    return response.json()["items"][position]


def test_pending_becomes_reciprocal_when_room_cabinet_panel_created(admin_client, rack, institution, env):
    c = admin_client
    cabinet, devices = rack
    a_url, aa = panel(c, cabinet)
    a = a_url + "/ports/" + aa[0]["id"]
    payload = dict(
        number="1", device_id=devices[0][0], interface_id=devices[0][1], external=target(cabinet, devices)
    )
    saved = c.put(a, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["external_status"] == "pending"
    _, b_cabinet = remote(c, cabinet, institution)
    assert row(c, a_url)["external_status"] == "pending"
    b_url, bb = panel(c, b_cabinet)
    ar, br = row(c, a_url), row(c, b_url)
    assert ar["peer_port_id"] == bb[0]["id"] and br["peer_port_id"] == aa[0]["id"]
    assert ar["external_status"] == br["external_status"] == "connected"
    assert br["device_id"] == devices[1][0] and br["interface_id"] == devices[1][1]
    assert ar["external"]["device_id"] == devices[1][0]
    assert br["external"]["device_id"] == devices[0][0]
    assert br["external"]["cabinet_id"] == cabinet["id"]
    reverse = c.get(f"/api/v1/devices/{devices[1][0]}/patch-ports").json()["items"]
    assert len(reverse) == 1 and reverse[0]["external"]["device_id"] == devices[0][0]
    assert c.put(a, json=payload).status_code == 200
    assert (
        c.put(a, json={"number": "1", "device_name": "Manual endpoint", "port_name": "eth7"}).status_code
        == 200
    )
    assert row(c, b_url)["external"]["device_name"] == "Manual endpoint"
    assert row(c, b_url)["external"]["port_name"] == "eth7"
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 2
        assert db.scalar(select(func.count()).select_from(m.Interface)) == 2
        revision = db.get(m.SystemState, "patch-cabling").value
    row(c, a_url)
    with env() as db:
        assert db.get(m.SystemState, "patch-cabling").value == revision  # GET never writes.
    assert c.put(a, json={"number": "1", "external": None}).status_code == 200
    assert row(c, a_url)["external"] is None and row(c, b_url)["external"] is None
    assert row(c, b_url)["device_id"] == devices[1][0]  # Front connection is preserved.


def test_existing_target_conflicts_and_self_reference_roll_back(admin_client, rack, institution):
    c = admin_client
    cabinet, devices = rack
    a_url, aa = panel(c, cabinet)
    _, b_cabinet = remote(c, cabinet, institution)
    b_url, bb = panel(c, b_cabinet)
    a = a_url + "/ports/" + aa[0]["id"]
    spec = {"port_id": bb[0]["id"], "device_id": devices[1][0], "interface_id": devices[1][1]}
    assert c.put(a, json={"number": "1", "external": spec}).status_code == 200
    response = c.put(a_url + "/ports/" + aa[1]["id"], json={"number": "changed", "external": spec})
    assert response.status_code == 409
    assert row(c, a_url, 1)["number"] == "2" and row(c, a_url, 1)["external"] is None
    assert c.put(a, json={"number": "1", "external": {"port_id": aa[0]["id"]}}).status_code == 422
    assert row(c, a_url)["peer_port_id"] == bb[0]["id"]
    # Different internal assignment must not be overwritten through the other end.
    assert (
        c.put(
            a,
            json={
                "number": "1",
                "external": {**spec, "device_id": devices[0][0], "interface_id": devices[0][1]},
            },
        ).status_code
        == 409
    )
    assert row(c, b_url)["device_id"] == devices[1][0]
    assert (
        c.put(
            a, json={"number": "1", "external": {**target(cabinet, devices), "interface_id": devices[0][1]}}
        ).status_code
        == 422
    )
    assert (
        c.put(a_url, json={"name": "FIBER-01", "kind": "cat", "start_unit": 2, "port_count": 2}).status_code
        == 409
    )


def test_pending_claims_are_not_resolved_arbitrarily(admin_client, rack, institution):
    c = admin_client
    cabinet, devices = rack
    a_url, aa = panel(c, cabinet)
    spec = target(cabinet, devices)
    for n in (0, 1):
        assert (
            c.put(a_url + "/ports/" + aa[n]["id"], json={"number": str(n + 1), "external": spec}).status_code
            == 200
        )
    _, b_cabinet = remote(c, cabinet, institution)
    b_url, bb = panel(c, b_cabinet)
    assert row(c, a_url)["external_status"] == row(c, a_url, 1)["external_status"] == "ambiguous"
    assert row(c, b_url)["peer_port_id"] is None
    assert (
        c.put(
            a_url + "/ports/" + aa[0]["id"],
            json={"number": "1", "external": {"port_id": bb[0]["id"], "device_id": devices[1][0]}},
        ).status_code
        == 200
    )
    assert row(c, a_url, 1)["external_status"] == "conflict"


def test_recreated_remote_panel_and_room_reconnect_automatically(admin_client, rack, institution):
    c = admin_client
    cabinet, devices = rack
    a_url, aa = panel(c, cabinet)
    room, b_cabinet = remote(c, cabinet, institution)
    b_url, bb = panel(c, b_cabinet)
    endpoint = a_url + "/ports/" + aa[0]["id"]
    assert (
        c.put(
            endpoint,
            json={
                "number": "1",
                "external": {
                    "port_id": bb[0]["id"],
                    "device_id": devices[1][0],
                    "interface_id": devices[1][1],
                },
            },
        ).status_code
        == 200
    )
    assert c.delete(b_url).status_code == 204
    assert row(c, a_url)["external_status"] == "pending"
    b_url, bb = panel(c, b_cabinet)
    assert row(c, a_url)["peer_port_id"] == bb[0]["id"]
    assert row(c, b_url)["device_id"] == devices[1][0]
    assert c.post("/api/v1/ipam/rooms/bulk-delete", json={"ids": [room["id"]]}).status_code == 200
    assert row(c, a_url)["external_status"] == "pending"
    _, b_cabinet = remote(c, cabinet, institution)
    b_url, bb = panel(c, b_cabinet)
    assert row(c, a_url)["peer_port_id"] == bb[0]["id"]


def test_pending_port_created_on_resize_and_ambiguous_room_names(admin_client, rack, institution):
    c = admin_client
    cabinet, devices = rack
    a_url, aa = panel(c, cabinet)
    _, b_cabinet = remote(c, cabinet, institution)
    b_url, bb = panel(c, b_cabinet)
    spec = {**target(cabinet, devices), "port_number": "3"}
    assert c.put(a_url + "/ports/" + aa[0]["id"], json={"number": "1", "external": spec}).status_code == 200
    assert row(c, a_url)["external_status"] == "pending"
    assert (
        c.put(b_url, json=dict(name="FIBER-01", kind="fiber", start_unit=2, port_count=3)).status_code == 200
    )
    assert row(c, a_url)["peer_port_id"] == row(c, b_url, 2)["id"]
    assert (
        c.put(b_url, json=dict(name="FIBER-01", kind="fiber", start_unit=2, port_count=2)).status_code == 409
    )
    _, duplicate = remote(c, cabinet, institution)
    panel(c, duplicate)
    assert (
        c.put(
            a_url + "/ports/" + aa[1]["id"], json={"number": "2", "external": target(cabinet, devices)}
        ).status_code
        == 200
    )
    assert row(c, a_url, 1)["external_status"] == "ambiguous"


def test_existing_pending_target_is_not_overwritten(admin_client, rack, institution):
    c = admin_client
    cabinet, devices = rack
    a_url, aa = panel(c, cabinet)
    _, b_cabinet = remote(c, cabinet, institution)
    b_url, bb = panel(c, b_cabinet)
    waiting = {**target(cabinet, devices), "room_name": "Another future room"}
    assert (
        c.put(b_url + "/ports/" + bb[0]["id"], json={"number": "1", "external": waiting}).status_code == 200
    )
    assert (
        c.put(
            a_url + "/ports/" + aa[0]["id"], json={"number": "1", "external": {"port_id": bb[0]["id"]}}
        ).status_code
        == 409
    )
    assert row(c, b_url)["external"]["room_name"] == "Another future room"
    assert row(c, a_url)["external"] is None


def test_port_list_fetches_reciprocal_metadata_in_one_batch(admin_client, rack, institution, env):
    from netrix.ipam.patch_panels import ports
    from test_read_performance import queries

    c = admin_client
    cabinet, _ = rack
    a_url, aa = panel(c, cabinet, count=100)
    _, b_cabinet = remote(c, cabinet, institution)
    _, bb = panel(c, b_cabinet)
    assert (
        c.put(
            a_url + "/ports/" + aa[0]["id"], json={"number": "1", "external": {"port_id": bb[0]["id"]}}
        ).status_code
        == 200
    )
    with env() as db:
        with queries() as sql:
            result = ports(db, cabinet["id"], aa[0]["panel_id"])
        assert len(result["items"]) == 100
        assert len(sql) <= 3
        assert result["items"][0]["external"]["port_id"] == bb[0]["id"]



def test_current_patch_descriptions_lock_only_required_rows_on_postgresql():
    db = Mock()
    db.execute.return_value = []
    patch_links.descriptions(db, ids={"port-id"}, current=True)

    statement = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "FOR SHARE OF patch_ports, patch_panels, cabinets" in str(statement)
