"""Physical endpoints must win over transit FDB observations without using inventory."""

from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import jobs, service
from netrix.ipam.connections import device_name
from test_ipam_endpoint_connections import endpoint, switch


def neighbor(port, name, **data):
    return {"interface_name": port, "remote_name": name, "evidence": {"lldp": data}}


def test_source_label_is_not_the_physical_device_name(admin_client, inventory, env):
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        port = switch(db, vlan.vrf_id, "IPAM · Core · 192.0.2.200")
        port.config.host = "192.0.2.200"
        assert device_name(port.config) == "Core"
        port.config.evidence = {**port.config.evidence, "hostname": "Actual-core"}
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == "Actual-core"


@pytest.mark.parametrize("same_mac", [True, False])
def test_direct_neighbor_wins_over_transit_even_when_chassis_mac_differs(
    admin_client, inventory, env, same_mac
):
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        row.hostname = "access-01.example.test"
        core = switch(db, vlan.vrf_id, "Core-01")
        core.config.kind = "backbone_switch"
        core.name = "H1"
        core.config.evidence = {
            **core.config.evidence,
            "neighbors": [
                neighbor(
                    "H1",
                    "ACCESS-01",
                    chassis_subtype=4,
                    chassis_id="00:50:56:a0:42:c0" if same_mac else "00:50:56:a0:42:aa",
                )
            ],
        }
        transit = switch(db, vlan.vrf_id, "Core-02")
        transit.config.kind = "backbone_switch"
        transit.name = "Trk1"
        db.commit()
        result = service.enrich(db, [row])[0]
        assert (result["connected_device"], result["connected_port"]) == ("Core-01", "H1")
        assert not result["connection_ambiguous"]
        assert not list(db.query(m.Device))


def test_multiple_direct_nics_without_fdb_are_preserved_and_duplicate_names_rejected(
    admin_client, inventory, env
):
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        row.hostname = "sv-vw-05.example.test"
        core = switch(db, vlan.vrf_id, "Core-01")
        core.config.kind = "backbone_switch"
        core.config.evidence = {
            "interfaces": [{"name": "A7", "if_index": 7}, {"name": "B7", "if_index": 39}],
            "neighbors": [
                neighbor(p, "VMware ESXi", chassis_subtype=7, chassis_id=row.hostname) for p in ["A7", "B7"]
            ],
        }
        second = switch(db, vlan.vrf_id, "Core-02")
        second.config.kind = "backbone_switch"
        second.config.evidence = {
            "interfaces": [{"name": "A6", "if_index": 6}],
            "neighbors": [neighbor("A6", row.hostname)],
        }
        db.commit()
        result = service.enrich(db, [row])[0]
        assert [(g["device_name"], g["port_label"]) for g in result["connection_groups"]] == [
            ("Core-01", "A7-B7"),
            ("Core-02", "A6"),
        ]
        # Name ambiguity is checked against all IPs, including off-page rows.
        other = m.IPAddress(vlan_id=vlan.id, vrf_id=vlan.vrf_id, address="192.0.2.12", hostname=row.hostname)
        db.add(other)
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == ""
        other.hostname = "different.example.test"
        core.config.last_success_at = second.config.last_success_at = now() - timedelta(hours=25)
        db.commit()
        assert service.enrich(db, [row])[0]["connected_device"] == ""


def test_trunk_without_neighbor_proof_is_not_an_endpoint(admin_client, inventory, env):
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        core = switch(db, vlan.vrf_id, "Transit")
        core.name = "Trk1"
        db.commit()
        result = service.enrich(db, [row])[0]
        assert result["connected_device"] == "" and result["connection_ambiguous"]


async def test_firewall_collects_identity_but_gateway_arp_is_not_an_attachment(admin_client, inventory, env):
    profile = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "FW SNMP",
            "protocol": "snmpv2c",
            "secret": {"community": "fixture-only"},
        },
    )
    assert profile.status_code == 201, profile.text
    response = admin_client.post(
        "/api/v1/integrations",
        json={
            "name": "Firewall",
            "kind": "firewall",
            "host": "192.0.2.1",
            "port": 161,
            "credential_id": profile.json()["id"],
            "enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        db.query(m.IPObservation).delete()
        job = m.Job(kind="integration", target_id=response.json()["id"])
        db.add(job)
        db.commit()
        job_id, row_id = job.id, row.id

    class Collector:
        async def collect(self, host, port, secret):
            assert host == "192.0.2.1" and secret["protocol"] == "snmpv2c"
            return {
                "hostname": "FW-01",
                "interfaces": [{"name": "VLAN20", "if_index": 20}],
                "tables": {"arp_mac": {"20.192.0.2.11": "00:50:56:a0:42:c0"}},
            }

    await jobs.integration(job_id, Collector())
    with env() as db:
        row = db.get(m.IPAddress, row_id)
        item = service.enrich(db, [row])[0]
        assert item["mac_address"] == "00:50:56:a0:42:c0"
        assert item["sources"] == ["firewall"]
        assert item["connected_device"] == item["connected_port"] == ""
        service.observe(
            db,
            db.get(m.VLAN, row.vlan_id),
            row.address,
            "windows_dhcp",
            "dhcp",
            {"mac_address": "00:11:22:33:44:55"},
        )
        db.commit()
        assert service.enrich(db, [row])[0]["mac_address"] == "00:11:22:33:44:55"


def test_changing_source_target_discards_old_attachment_evidence(admin_client, inventory, env):
    with env() as db:
        vlan, row = endpoint(db, inventory["vrf"]["id"])
        source = switch(db, vlan.vrf_id, "Switch")
        source.config.credential_id = inventory["credential"]["id"]
        db.commit()
        source_id = source.config.id
        assert service.enrich(db, [row])[0]["connected_device"] == "Switch"
    response = admin_client.put(
        "/api/v1/integrations/" + source_id,
        json={
            "name": "Switch",
            "kind": "corner_switch",
            "host": "192.0.2.99",
            "port": 161,
            "enabled": True,
            "credential_id": inventory["credential"]["id"],
        },
    )
    assert response.status_code == 200, response.text
    with env() as db:
        config = db.get(m.Integration, source_id)
        assert config.evidence == {} and config.last_success_at is None
