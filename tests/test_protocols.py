from types import SimpleNamespace

import pytest
from netrix.core import settings
from netrix.discovery import protocols as p
from netrix.discovery.correlation import correlate


class Engine:
    closed = False

    def close_dispatcher(self):
        self.closed = True


class Transport:
    @classmethod
    async def create(cls, address, **kwargs):
        assert kwargs["timeout"] == 2 and kwargs["retries"] == 1
        return address


class MAC:
    def asOctets(self):
        return bytes.fromhex("aabbccddeeff")


async def test_snmpv3_adapter_parses_standard_tables_and_closes_transport(monkeypatch):
    instance = Engine()
    monkeypatch.setattr(p, "SnmpEngine", lambda: instance)
    monkeypatch.setattr(p, "UdpTransportTarget", Transport)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)

    async def get(*args, **kwargs):
        return (
            None,
            0,
            0,
            [
                (oid, v)
                for oid, v in zip(
                    p.SYSTEM.values(), ["Fixture switch", "1.3.6.1.4.1", 100000, "edge-observed"]
                )
            ],
        )

    async def walk(engine, auth, target, context, oid, **kwargs):
        assert kwargs["lexicographicMode"] is False
        assert kwargs["maxRows"] == 2048
        table = {
            p.TABLES["if_descr"]: {"1": "GigabitEthernet1"},
            p.TABLES["if_name"]: {"1": "Gi1"},
            p.TABLES["if_mac"]: {"1": MAC()},
            p.TABLES["if_speed"]: {"1": 1000},
            p.TABLES["if_status"]: {"1": 1},
            p.TABLES["in_octets"]: {"1": 1000},
            p.TABLES["out_octets"]: {"1": 2000},
            p.TABLES["discontinuity"]: {"1": 0},
            p.TABLES["lldp_local_id"]: {"1": "Gi1"},
            p.TABLES["lldp_name"]: {"0.1.1": "peer"},
            p.TABLES["lldp_port"]: {"0.1.1": "Gi2"},
        }.get(oid, {})
        for index, value in table.items():
            yield None, 0, 0, [(oid + "." + index, value)]

    monkeypatch.setattr(p, "get_cmd", get)
    monkeypatch.setattr(p, "walk_cmd", walk)
    data = await p.SNMPCollector().collect(
        "192.0.2.1", 161, {"username": "user", "auth_key": "fixture-auth", "priv_key": "fixture-priv"}
    )
    assert data["hostname"] == "edge-observed"
    port = data["interfaces"][0]
    assert port["speed_bps"] == 1000000000 and port["counters"]["in_octets"] == 1000
    assert port["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert data["neighbors"][0]["remote_name"] == "peer"
    assert instance.closed


async def test_snmp_failure_is_sanitized_and_dispatcher_closed(monkeypatch):
    instance = Engine()
    monkeypatch.setattr(p, "SnmpEngine", lambda: instance)
    monkeypatch.setattr(p, "UdpTransportTarget", Transport)

    async def fail(*args, **kwargs):
        return "contains-secret", 0, 0, []

    monkeypatch.setattr(p, "get_cmd", fail)
    with pytest.raises(p.NetworkError) as e:
        await p.SNMPCollector().collect(
            "192.0.2.1", 161, {"username": "user", "auth_key": "fixture-auth", "priv_key": "fixture-priv"}
        )
    assert "contains-secret" not in str(e.value)
    assert instance.closed


async def test_ssh_adapter_keeps_host_key_verification(env, monkeypatch):
    class Connection:
        async def run(self, command, **kwargs):
            assert command == "show running-config" and kwargs["timeout"] == 60
            return SimpleNamespace(stdout="hostname fixture")

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            pass

    def connect(host, **kwargs):
        assert kwargs["known_hosts"] == settings().known_hosts
        assert kwargs["client_keys"] == []
        return Context()

    monkeypatch.setattr(p.asyncssh, "connect", connect)
    device = SimpleNamespace(adapter="ios", management_ip="192.0.2.1", config_port=22)
    assert (
        await p.fetch_config(device, {"username": "fixture", "password": "fixture-secret"})
        == "hostname fixture"
    )


def test_arp_ndp_fdb_candidates_keep_ambiguous_ports():
    mac = "aa:bb:cc:dd:ee:ff"
    suffix = "170.187.204.221.238.255"
    ndp_index = "1.2.16." + ".".join(str(v) for v in bytes.fromhex("20010db8000000000000000000000001"))
    tables = {
        "arp_mac": {"1.192.0.2.1": mac},
        "ndp_mac": {ndp_index: mac},
        "fdb_port": {suffix: "2"},
        "bridge_ifindex": {"2": "10", "3": "11"},
    }
    candidates = correlate(tables, [])
    assert {row["ip"] for row in candidates} == {"192.0.2.1", "2001:db8::1"}
    assert all(row["ifindex_candidates"] == ["10"] for row in candidates)
    tables["vlan_fdb_port"] = {"20." + suffix: "3"}
    candidates = correlate(tables, [{"interface_name": "uplink"}])
    assert all(row["ambiguous"] and row["confidence"] < 0.5 for row in candidates)
