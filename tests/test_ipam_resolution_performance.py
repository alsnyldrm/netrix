from datetime import timedelta

from netrix import models as m
from netrix.core import now
from netrix.ipam import service, table
from sqlalchemy import select
from test_ipam_endpoint_connections import endpoint, switch


def test_server_neighbor_bond_is_not_a_transit_uplink(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        switch(db, prefix.vrf_id, "Upstream", uplink=True)
        port = switch(db, prefix.vrf_id, "Backbone")
        port.name = "Trk2"
        snapshot = db.scalar(select(m.Observation).where(m.Observation.device_id == port.device_id))
        snapshot.evidence = {
            **snapshot.evidence,
            "neighbors": [
                {
                    "interface_name": f"C{i}",
                    "remote_name": "sv-id-01",
                    "remote_port": f"mgmt_{i - 17:02}",
                    "evidence": {
                        "cdp": {"management_address": row.address},
                        "local_aggregate": {"name": "Trk2"},
                    },
                }
                for i in range(17, 21)
            ],
            "neighbor_detail": {"spanning_tree": {"port": "Trk1"}},
        }
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "Backbone"
        assert result["connected_port"] == "Trk2"
        assert result["hostname"] == "sv-id-01"
        assert not result["connection_ambiguous"]
        assert result["connection_members"] == ["C17", "C18", "C19", "C20"]


def test_table_returns_summary_without_raw_evidence(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        switch(db, prefix.vrf_id, "Access")
        db.commit()
        item = table.addresses(db, prefix, allocated=True)["items"][0]
        assert item["connected_device"] == "Access"
        assert "observations" not in item and "connections" not in item
        assert service.enrich(db, [row])[0]["observations"]


def test_dhcp_identity_precedes_newer_switch_observation(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        service.observe(
            db,
            prefix,
            row.address,
            "windows_dhcp",
            "dhcp",
            {"hostname": "dhcp-host", "mac_address": "00:50:56:a0:42:c0"},
        )
        service.observe(
            db,
            prefix,
            row.address,
            "inventory",
            "switch",
            {"hostname": "switch-old-name", "mac_address": "00:50:56:a0:99:99"},
        )
        db.commit()
        value = service.enrich(db, [row])[0]
        assert value["hostname"] == "dhcp-host"
        assert value["mac_address"] == "00:50:56:a0:42:c0"
        assert value["mac_conflict"]


def test_corner_then_backbone_then_firewall_arp(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        corner = switch(db, prefix.vrf_id, "Corner")
        backbone = switch(db, prefix.vrf_id, "Backbone", uplink=True)
        db.add(m.DeviceType(code="bb", name="Backbone Switch"))
        db.flush()
        db.get(m.Device, backbone.device_id).kind = "bb"
        o = db.scalar(select(m.Observation).where(m.Observation.device_id == backbone.device_id))
        o.evidence = {**o.evidence, "neighbors": []}
        firewall = m.Device(
            name="Firewall", management_ip="192.0.2.23", vrf_id=prefix.vrf_id, kind="firewall"
        )
        db.add(firewall)
        db.flush()
        fwport = m.Interface(device_id=firewall.id, name="VLAN-020", if_index=20)
        job = m.Job(kind="monitor", target_id=firewall.id)
        db.add_all([fwport, job])
        db.flush()
        db.add(
            m.Observation(
                device_id=firewall.id,
                job_id=job.id,
                address=firewall.management_ip,
                evidence={"tables": {"arp_mac": {"20.192.0.2.11": "00:50:56:a0:42:c0"}}},
            )
        )
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Corner"
        db.get(m.Device, corner.device_id).archived = True
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Backbone"
        db.get(m.Device, backbone.device_id).archived = True
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "" and result["connected_port"] == ""
        assert service.physical_connections(result["connections"]) == []


def test_latest_snapshot_cache_refreshes_on_change_and_expiry(admin_client, inventory, env, monkeypatch):
    from netrix.ipam import connections

    calls = []
    original = connections.project_snapshot

    def project(evidence):
        calls.append(1)
        return original(evidence)

    monkeypatch.setattr(connections, "project_snapshot", project)
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        port = switch(db, prefix.vrf_id, "Access")
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Access"
        count = len(calls)
        assert service.enrich(db, [row])[0]["connected_device"] == "Access"
        assert len(calls) == count
        o = db.scalar(select(m.Observation).where(m.Observation.device_id == port.device_id))
        o.evidence = {"tables": {}}
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == ""
        assert len(calls) > count
        o.created_at = now() - timedelta(hours=25)
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == ""


def test_response_cache_invalidation_expiry_and_failure(env, monkeypatch):
    import json

    from netrix import services
    from netrix.ipam import read_cache

    memory = services.redis_client()
    monkeypatch.setattr(read_cache, "client", lambda _: memory)
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    calls = []

    def load():
        calls.append(1)
        return {"generation": len(calls)}

    def read(key="prefix-a"):
        return json.loads(read_cache.json_response([key], load).body)

    assert read()["generation"] == 1
    assert read()["generation"] == 1
    services.publish()
    assert read()["generation"] == 2
    assert read("prefix-b")["generation"] == 3
    current = read_cache.time.time()
    monkeypatch.setattr(read_cache.time, "time", lambda: current + 6)
    assert read()["generation"] == 4

    def unavailable(_):
        raise ConnectionError("cache unavailable")

    monkeypatch.setattr(read_cache, "client", unavailable)
    assert read()["generation"] == 5
    assert read()["generation"] == 6


def test_cached_table_still_requires_authentication(admin_client, inventory, env, monkeypatch):
    from netrix import services
    from netrix.ipam import read_cache

    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        db.commit()
        url = f"/api/v1/ipam/prefixes/{prefix.id}/addresses?allocated=true"
    first = admin_client.get(url)
    assert first.status_code == 200
    cached = admin_client.get(url)
    assert "hit" in cached.headers["Server-Timing"]
    admin_client.post("/api/v1/auth/logout")
    assert admin_client.get(url).status_code == 401


def test_dhcp_active_leases_and_reservations_have_distinct_status():
    from netrix.ipam.adapters import DHCP_SCRIPT, dhcp_records

    rows = dhcp_records(
        b'[{"address":"192.0.2.5","hostname":"lease","reserved":false}, {"address":"192.0.2.6","hostname":"reservation","reserved":true}, {"address":"192.0.2.6","hostname":"lease-duplicate","reserved":false}]'
    )
    assert len(rows) == 2
    assert not rows[0]["reserved"]
    assert rows[1]["reserved"] and rows[1]["hostname"] == "reservation"
    assert "Get-DhcpServerv4Lease" in DHCP_SCRIPT and "-AllLeases" not in DHCP_SCRIPT


def test_ap_neighbor_mac_is_endpoint_not_transit(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        port = switch(db, prefix.vrf_id, "AP access", uplink=True)
        snapshot = db.scalar(select(m.Observation).where(m.Observation.device_id == port.device_id))
        snapshot.evidence = {
            **snapshot.evidence,
            "neighbors": [
                {
                    "interface_name": port.name,
                    "remote_name": "ap-01",
                    "evidence": {"lldp": {"chassis_subtype": 4, "chassis_id": "00:50:56:a0:42:c0"}},
                }
            ],
        }
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "AP access"
        assert result["connected_port"] == port.name
        # A MAC learned behind that AP must not be assigned to its uplink.
        service.observe(db, prefix, row.address, "inventory", "gw", {"mac_address": "00:50:56:a0:42:c1"})
        snapshot.evidence = {
            **snapshot.evidence,
            "tables": {"fdb_port": {"0.80.86.160.66.193": "3"}, "bridge_ifindex": {"3": "7"}},
        }
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == ""


def test_operator_topology_endpoint_precedes_other_nic_fdb(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        row.hostname = "sv-id-01"
        switch(db, prefix.vrf_id, "Management")
        port = switch(db, prefix.vrf_id, "Data", uplink=True)
        port.name = "Trk1"
        snapshot = db.scalar(select(m.Observation).where(m.Observation.device_id == port.device_id))
        snapshot.evidence = {"tables": {}}
        for member in ["A2", "B2"]:
            db.add(
                m.Link(
                    device_id=port.device_id,
                    interface_name=member,
                    remote_name="NIC hardware label",
                    remote_port="NIC",
                    manual_remote_name="SV-ID-01.example.test",
                    manual_remote_port="backbone",
                    last_seen_at=now(),
                    evidence={"local_aggregate": {"name": "Trk1"}},
                )
            )
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "Data"
        assert result["connected_port"] == "A2 / B2"
        assert result["connection_members"] == ["A2", "B2"]
        # Editing/removing managed topology must immediately change the projection.
        for link in db.scalars(select(m.Link).where(m.Link.device_id == port.device_id)):
            link.is_current = False
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Management"


def test_neighbor_identity_can_find_managed_backbone_without_dns(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        management = switch(db, prefix.vrf_id, "Management")
        observation = db.scalar(select(m.Observation).where(m.Observation.device_id == management.device_id))
        observation.evidence = {
            **observation.evidence,
            "neighbors": [
                {
                    "interface_name": management.name,
                    "remote_name": "sv-id-01",
                    "evidence": {"cdp": {"management_address": row.address}},
                }
            ],
        }
        data = switch(db, prefix.vrf_id, "Data", uplink=True)
        link = m.Link(
            device_id=data.device_id,
            interface_name=data.name,
            remote_name="NIC",
            remote_port="NIC",
            manual_remote_name="SV-ID-01.example.test",
            last_seen_at=now(),
        )
        db.add(link)
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Data"
        for field, value in [
            ("auto_add_excluded", True),
            ("is_current", False),
            ("last_seen_at", now() - timedelta(hours=25)),
        ]:
            original = getattr(link, field)
            setattr(link, field, value)
            db.commit()
            assert service.enrich(db, [row])[0]["connected_device"] == "Management"
            setattr(link, field, original)
        # A correction naming a different FQDN is not an identity match.
        row.hostname = "sv-id-01.other.test"
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Management"


def test_conflicting_managed_endpoints_stay_ambiguous(admin_client, inventory, env):
    with env() as db:
        prefix, row = endpoint(db, inventory["vrf"]["id"])
        row.hostname = "server.example.test"
        first = switch(db, prefix.vrf_id, "Corner")
        second = switch(db, prefix.vrf_id, "Backbone", uplink=True)
        db.add(m.DeviceType(code="bb", name="Backbone Switch"))
        db.flush()
        db.get(m.Device, second.device_id).kind = "bb"
        for port in [first, second]:
            db.add(
                m.Link(
                    device_id=port.device_id,
                    interface_name=port.name,
                    remote_name="NIC",
                    remote_port="NIC",
                    manual_remote_name=row.hostname,
                    last_seen_at=now(),
                )
            )
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == ""
        assert result["connection_ambiguous"]
