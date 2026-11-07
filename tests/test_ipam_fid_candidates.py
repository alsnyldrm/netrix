"""No real devices: missing-FID fallback must validate VLAN, MAC, port and peers."""

from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from netrix.core import now
from netrix.discovery import fid_candidates as fid
from netrix.discovery import point
from netrix.discovery import protocols as p
from pysnmp.proto.rfc1902 import OctetString

MAC = "00:11:22:33:44:55"
SUFFIX = "0.17.34.51.68.85"


def hint(fids=(700,)):
    return {
        "fdb_at": now().isoformat(),
        "neighbor_protocols_complete": ["lldp"],
        "tables": {
            "vlan_fdb_id": {},
            "vlan_fdb_port": {f"{v}.{SUFFIX}": "9" for v in fids},
            "vlan_fdb_status": {f"{v}.{SUFFIX}": "3" for v in fids},
            "bridge_ifindex": {"9": "101"},
            "if_name": {"101": "A7"},
            "lldp_local_id": {"1": "A7"},
        },
    }


class Query:
    def __init__(self, mapping=None, status=3, up=1, bitmap=b"\x00\x80", neighbor=False):
        self.mapping = mapping or {}
        self.status, self.up, self.bitmap, self.neighbor = status, up, bitmap, neighbor
        self.calls = []
        self.walks = []

    async def metadata(self, oid, **_):
        self.walks.append(oid)
        assert oid not in (p.IPAM_TABLES["vlan_fdb_port"], p.IPAM_TABLES["vlan_fdb_status"])
        if oid == p.IPAM_TABLES["vlan_fdb_id"]:
            return self.mapping
        if oid == p.IPAM_TABLES["lldp_local_id"]:
            return {"1": "A7"}
        if oid == p.IPAM_TABLES["lldp_local_type"]:
            return {"1": "5"}
        if oid == p.IPAM_TABLES["lldp_chassis"] and self.neighbor:
            return {"0.1.1": "00:aa:bb:cc:dd:ee"}
        return {}

    async def get(self, oids):
        self.calls.extend(oids)
        result = {}
        for oid in oids:
            if oid.startswith(p.IPAM_TABLES["vlan_fdb_port"] + "."):
                assert oid.endswith("." + SUFFIX), "Must not query another MAC"
                result[oid] = 9
            elif oid.startswith(p.IPAM_TABLES["vlan_fdb_status"] + "."):
                result[oid] = self.status
            elif oid == fid.VLAN_EGRESS + ".20" and self.bitmap is not None:
                result[oid] = OctetString(self.bitmap)
            elif oid.startswith(p.IPAM_TABLES["bridge_ifindex"] + "."):
                result[oid] = 101
            elif oid.startswith(p.IPAM_TABLES["if_name"] + "."):
                result[oid] = "A7"
            elif oid.startswith(p.IPAM_TABLES["if_status"] + "."):
                result[oid] = self.up
            elif oid == "1.0.8802.1.1.2.1.2.1.0":
                result[oid] = 0
            elif self.neighbor:
                for key, value in {
                    "lldp_chassis": "00:aa:bb:cc:dd:ee",
                    "lldp_chassis_type": "4",
                    "lldp_name": "Downstream",
                    "lldp_port": "uplink",
                    "lldp_port_type": "5",
                }.items():
                    if oid == p.IPAM_TABLES[key] + ".0.1.1":
                        result[oid] = value
        return result


async def lookup(monkeypatch, query=None, data=None):
    query = query or Query()

    @asynccontextmanager
    async def reader(*_):
        yield query

    monkeypatch.setattr(point, "reader", reader)
    return await point.switch("198.51.100.2", 161, {}, MAC, 20, data or hint())


async def test_missing_mapping_validates_non_vlan_fid_with_snmp_only(monkeypatch):
    query = Query()
    result = await lookup(monkeypatch, query)
    assert result["ports"] == [
        {
            "port": "A7",
            "if_index": 101,
            "bridge_port": 9,
            "fdb_id": 700,
            "vlan_unmapped": True,
        }
    ]
    assert result["unmapped_fid"] and result["neighbors"] == []
    assert not any(".20." + SUFFIX in oid for oid in query.calls)
    assert fid.VLAN_EGRESS + ".20" in query.calls


@pytest.mark.parametrize("fault", ["stale", "failed", "unsupported", "no_timestamp", "no_mac"])
async def test_invalid_sql_hints_never_produce_a_live_candidate(monkeypatch, fault):
    data = hint()
    if fault == "stale":
        data["fdb_at"] = (now() - timedelta(hours=8)).isoformat()
    elif fault == "failed":
        data["failed"] = True
    elif fault == "unsupported":
        data["unsupported"] = ["vlan_fdb_status"]
    elif fault == "no_timestamp":
        data.pop("fdb_at")
    else:
        data["tables"]["vlan_fdb_port"] = {"700.0.17.34.51.68.86": "9"}
    query = Query()
    assert not (await lookup(monkeypatch, query, data))["ports"]
    assert query.calls == []


@pytest.mark.parametrize(
    "query",
    [
        Query(status=2),
        Query(status=4),
        Query(status=99),
        Query(up=2),
        Query(bitmap=b"\x00\x40"),
        Query(bitmap=None),
        Query(bitmap=b""),
    ],
)
async def test_rejects_invalid_mac_down_port_or_missing_vlan_membership(monkeypatch, query):
    assert not (await lookup(monkeypatch, query))["ports"]


@pytest.mark.parametrize("fids", [(700, 900), tuple(range(1, 18))])
async def test_independent_fids_are_not_arbitrarily_selected(monkeypatch, fids):
    with pytest.raises(p.NetworkError):
        await lookup(monkeypatch, data=hint(fids))


async def test_known_other_vlan_cannot_be_bypassed(monkeypatch):
    assert not (await lookup(monkeypatch, Query(mapping={"0.30": "700"})))["ports"]


async def test_refreshes_new_neighbor_not_present_in_sql(monkeypatch):
    result = await lookup(monkeypatch, Query(neighbor=True))
    assert result["neighbors"][0]["remote_name"] == "Downstream"
    assert result["neighbors"][0]["interface_name"] == "A7"


def test_qbridge_port_bitmap_is_one_based_high_bit_first():
    for port in (1, 8, 9, 17, 48):
        raw = bytearray(6)
        raw[(port - 1) // 8] |= 128 >> ((port - 1) % 8)
        assert fid.member(OctetString(bytes(raw)), port)
        assert not fid.member(OctetString(bytes(raw)), port + 1)


# Reuse the real API/SQL fixture; all protocol operations remain fake.
from test_ipam_source_contract import network as network  # noqa: E402


@pytest.mark.parametrize("fault", [None, "multi_mac", "uplink", "no_neighbors", "two_switches", "no_route"])
async def test_ipam_missing_fid_keeps_sql_identity_without_switch_probe(
    admin_client, network, monkeypatch, fault
):
    import json

    from netrix import models as m
    from netrix.identity.security import encrypt
    from netrix.ipam import adapters, point_sources
    from netrix.ipam.network import read_context
    from sqlalchemy import func, select

    sf, _, address_id, ids = network
    with sf() as db:
        leaf = db.get(m.Device, ids[1])
        core = db.get(m.Device, ids[2])
        core.name = "HP-SW-BB-ROOT"
        if fault == "two_switches":
            leaf.name = "HP-SW-BB-LEAF"
            for link in db.scalars(select(m.Link).where(m.Link.device_id == core.id)):
                db.delete(link)
        if fault == "no_route":
            for link in db.scalars(select(m.Link).where(m.Link.device_id == core.id)):
                db.delete(link)
            core_state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == core.id))
            core_state.mac_entries.append(
                m.SwitchMacEntry(
                    vrf_id=core.vrf_id,
                    vlan_vid=20,
                    fdb_id=900,
                    mac_address="00:11:22:33:44:77",
                    port="Gi1/0/1",
                    if_index=101,
                    bridge_port=3,
                    status="3",
                    observed_at=now(),
                    present=True,
                )
            )
        ssh = m.Credential(
            name="Unused SSH",
            protocol="ssh",
            encrypted_secret=encrypt(
                json.dumps(
                    {
                        "username": "fixture",
                        "password": "fixture",
                    }
                )
            ),
        )
        db.add(ssh)
        db.flush()
        leaf.adapter, leaf.config_credential_id = "aruba_5400", ssh.id
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == leaf.id))
        state.read_context = read_context(leaf, db.get(m.Credential, leaf.snmp_credential_id), ssh)
        state.vlan_fdbs = []
        for entry in state.mac_entries:
            entry.vlan_vid, entry.port = 0, "A7"
        for port in state.ports:
            port.name = "A7"
        if fault == "multi_mac":
            state.mac_entries.append(
                m.SwitchMacEntry(
                    vrf_id=leaf.vrf_id,
                    vlan_vid=0,
                    fdb_id=700,
                    mac_address="00:11:22:33:44:66",
                    port="A7",
                    if_index=101,
                    bridge_port=9,
                    status="3",
                    observed_at=now(),
                    present=True,
                )
            )
        if fault == "no_neighbors":
            state.lldp_complete = state.cdp_complete = False
        db.commit()

    async def ssh_forbidden(*_):
        raise AssertionError("Missing-FID fallback must never require SSH")

    async def ping(*_):
        return True

    async def dns(*_):
        return "target.example"

    query = Query(neighbor=fault == "uplink")

    @asynccontextmanager
    async def reader(*_):
        yield query

    class Collector:
        async def ipam_gateway(self, *_):
            return [MAC]

        async def ipam_switch(self, host, port, secret, mac, vid, data):
            if host == "198.51.100.2":
                data["tables"].update(lldp_local_id={"1": "A7"}, lldp_local_type={"1": "5"})
                return await point.switch(host, port, secret, mac, vid, data)
            return {"ports": [{"port": "Gi1/0/1", "if_index": 101}], "neighbors": []}

    monkeypatch.setattr(p, "fetch_neighbor_ports", ssh_forbidden)
    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    monkeypatch.setattr(point, "reader", reader)
    for _ in range(2):
        from netrix.ipam import pipeline

        with sf() as db:
            row = db.get(m.IPAddress, address_id)
            sources = point_sources.PointSources(db, row, db.get(m.VLAN, row.vlan_id), Collector())
        started = now()
        result = await pipeline.resolve(row.address, sources)
        with sf() as db:
            pipeline.save_result(db, db.get(m.IPAddress, address_id), started, result)
            db.commit()
        item = admin_client.get(f"/api/v1/ipam/addresses/{address_id}").json()
        # No live VLAN/FID validation is permitted in IPAM. A7 lacks SQL proof.
        assert item["connected_port"] != "A7"
        assert query.calls == [] and query.walks == []
        with sf() as db:
            entries = list(
                db.scalars(
                    select(m.SwitchMacEntry)
                    .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SwitchMacEntry.snapshot_id)
                    .where(m.IPAMNetworkState.device_id == ids[1], m.SwitchMacEntry.mac_address == MAC)
                )
            )
            assert len(entries) == 1 and entries[0].fdb_id == 700 and entries[0].vlan_vid == 0
            assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1


@pytest.mark.parametrize("origin", ["schedule", "schedule_ssh_failure"])
async def test_vlan_scan_does_not_probe_when_inventory_fid_is_missing(
    admin_client, network, monkeypatch, origin
):
    from netrix import models as m
    from netrix import worker
    from netrix.ipam import adapters
    from sqlalchemy import select

    sf, vlan_id, address_id, ids = network
    with sf() as db:
        snapshots = {
            db.get(m.Device, s.device_id).management_ip: s.evidence
            for s in db.scalars(select(m.IPAMNetworkState))
        }
        data = snapshots["198.51.100.2"]
        data["tables"]["vlan_fdb_id"] = {}
        data["unsupported"] = ["vlan_fdb_id"]
        data["interfaces"][0]["name"] = "A7"
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        state.vlan_fdbs = []  # Device has never supplied a VLAN/FID mapping.
        state.evidence = data
        db.commit()

    if origin == "schedule_ssh_failure":
        import json

        from netrix.identity.security import encrypt

        with sf() as db:
            leaf = db.get(m.Device, ids[1])
            ssh = m.Credential(
                name="Optional SSH",
                protocol="ssh",
                encrypted_secret=encrypt(json.dumps({"username": "fixture", "password": "fixture"})),
            )
            db.add(ssh)
            db.flush()
            leaf.adapter, leaf.config_credential_id = "aruba_5400", ssh.id
            db.commit()

        async def unavailable(*_):
            raise p.NetworkError("Fixture SSH unavailable")

        monkeypatch.setattr(p, "fetch_neighbor_detail", unavailable)

    class Collector:
        async def ipam(self, host, *_):
            assert host == "198.51.100.1", "IPAM must never read a switch"
            return snapshots[host]

        async def ipam_gateway(self, *_):
            return [MAC]

        async def ipam_switch(self, host, port, secret, mac, vid, data):
            if host == "198.51.100.3":
                return {"ports": [{"port": "Gi1/0/1", "if_index": 101}], "neighbors": []}
            assert host == "198.51.100.2"
            return await point.switch(host, port, secret, mac, vid, data)

    @asynccontextmanager
    async def reader(*_):
        yield Query()

    async def ping(*_):
        return True

    async def dns(*_):
        return "target.example"

    monkeypatch.setattr(point, "reader", reader)
    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    monkeypatch.setattr("netrix.ipam.vlan_pipeline.targets", lambda *_: ["192.0.2.10"])
    job = admin_client.post(f"/api/v1/ipam/vlans/{vlan_id}/discover").json()
    if origin != "manual":
        with sf() as db:
            row = db.get(m.Job, job["id"])
            row.result = {**row.result, "ipam_origin": "schedule"}
            db.commit()
    assert worker.claim(interactive=False, include_kinds=("ipam_discover",)) == job["id"]
    await worker.execute(job["id"], Collector())
    item = admin_client.get(f"/api/v1/ipam/addresses/{address_id}").json()
    assert item["scan_status"] == "problem", item["scan_result"]
    assert not item["connected_port"]
    with sf() as db:
        assert not list(db.get(m.IPAMNetworkState, state.id).vlan_fdbs)


async def test_missing_neighbor_protocol_does_not_prove_an_empty_edge(monkeypatch):
    class NoProtocol(Query):
        async def get(self, oids):
            result = await super().get(oids)
            result.pop("1.0.8802.1.1.2.1.2.1.0", None)
            return result

    with pytest.raises(p.NetworkError):
        await lookup(monkeypatch, NoProtocol())
