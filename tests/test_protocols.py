from types import SimpleNamespace

import pytest
from netrix.core import settings
from netrix.discovery import protocols as p
from netrix.discovery.correlation import correlate
from pysnmp.proto.rfc1902 import OctetString


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


@pytest.mark.parametrize("version", ["snmpv3", "snmpv2c"])
async def test_snmp_adapter_parses_standard_tables_and_closes_transport(monkeypatch, version):
    secret = (
        {"protocol": version, "community": "fixture-community"}
        if version == "snmpv2c"
        else {"username": "user", "auth_key": "fixture-auth", "priv_key": "fixture-priv"}
    )
    instance = Engine()
    monkeypatch.setattr(p, "SnmpEngine", lambda: instance)
    monkeypatch.setattr(p, "UdpTransportTarget", Transport)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)
    walked = []

    async def get(*args, **kwargs):
        auth = args[1]
        if version == "snmpv2c":
            assert isinstance(auth, p.CommunityData)
            assert auth.message_processing_model == 1 and auth.communityName == "fixture-community"
        else:
            assert isinstance(auth, p.UsmUserData)
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
        walked.append(oid)
        assert kwargs["lexicographicMode"] is False
        assert kwargs["maxRows"] == 2048
        table = {
            p.TABLES["entity_class"]: {"1": 3, "2": 9},
            p.TABLES["entity_vendor"]: {"1": "Cisco", "2": "Transceiver vendor"},
            p.TABLES["entity_model"]: {"1": "C9300-48P", "2": "SFP-10G"},
            p.TABLES["if_descr"]: {"1": "GigabitEthernet1"},
            p.TABLES["if_name"]: {"1": "Gi1"},
            p.TABLES["if_mac"]: {"1": MAC()},
            p.TABLES["if_speed"]: {"1": 1000},
            p.TABLES["if_status"]: {"1": 1},
            p.TABLES["cdp_name"]: {"1.1": OctetString(bytes.fromhex("187a3b4f1440")), "1.2": "device-id"},
            p.TABLES["cdp_sysname"]: {"1.2": "edge-sysname"},
            p.TABLES["cdp_port"]: {"1.1": OctetString(bytes.fromhex("ec0273652940"))},
            p.TABLES["lldp_local_id"]: {"1": "Gi1"},
            p.TABLES["lldp_name"]: {"0.1.1": "peer"},
            p.TABLES["lldp_port"]: {"0.1.1": "Gi2"},
        }.get(oid, {})
        for index, value in table.items():
            yield None, 0, 0, [(oid + "." + index, value)]

    monkeypatch.setattr(p, "get_cmd", get)
    monkeypatch.setattr(p, "walk_cmd", walk)
    data = await p.SNMPCollector().collect("192.0.2.1", 161, secret)
    assert data["hostname"] == "edge-observed"
    assert data["identity"] == {"vendor": "Cisco", "model": "C9300-48P", "kind": "switch"}
    port = data["interfaces"][0]
    assert port["speed_bps"] == 1000000000 and "counters" not in port
    assert not {"1.3.6.1.2.1.31.1.1.1.6", "1.3.6.1.2.1.31.1.1.1.10"} & set(walked)
    assert port["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert data["neighbors"][0]["remote_name"] == "peer"
    assert data["neighbors"][1]["remote_name"] == "18:7a:3b:4f:14:40"
    assert data["neighbors"][1]["remote_port"] == "ec:02:73:65:29:40"
    assert data["neighbors"][2]["remote_name"] == "edge-sysname"
    assert instance.closed
    walked.clear()
    data = await p.SNMPCollector().identify("192.0.2.1", 161, secret)
    assert data["identity"]["model"] == "C9300-48P" and "interfaces" not in data
    assert set(walked) == {oid for key, oid in p.TABLES.items() if key.startswith("entity_")}
    walked.clear()
    assert await p.SNMPCollector().probe("192.0.2.1", 1161, secret) is None
    assert walked == []  # The connection test performs GET only, never a full table scan.
    assert instance.closed

    class FastTransport:
        @classmethod
        async def create(cls, address, **kwargs):
            assert kwargs == {"timeout": 1, "retries": 1}
            return address

    monkeypatch.setattr(p, "UdpTransportTarget", FastTransport)
    assert await p.SNMPCollector().discovery_probe("192.0.2.1", 161, secret) is None
    assert walked == [] and instance.closed


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


@pytest.mark.parametrize("trust", [False, True])
async def test_ssh_adapter_keeps_host_key_verification(env, monkeypatch, trust):
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
        assert kwargs["known_hosts"] == (None if trust else settings().known_hosts)
        assert kwargs["client_keys"] == []
        return Context()

    monkeypatch.setattr(p.asyncssh, "connect", connect)
    device = SimpleNamespace(
        adapter="ios", management_ip="192.0.2.1", config_port=22, ssh_trust_host_key=trust
    )
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


@pytest.mark.parametrize("trust", [False, True])
async def test_ssh_identity_uses_read_only_command_and_verified_host(env, monkeypatch, trust):
    class Connection:
        async def run(self, command, **kwargs):
            assert command == "show version" and kwargs == {"check": True, "timeout": 30}
            return SimpleNamespace(stdout="Cisco IOS XE\nModel Number : C9300-48P\n")

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            pass

    def connect(host, **kwargs):
        assert host == "192.0.2.1" and kwargs["port"] == 2222
        assert (
            kwargs["known_hosts"] == (None if trust else settings().known_hosts)
            and kwargs["client_keys"] == []
        )
        assert kwargs["connect_timeout"] == 10 and kwargs["login_timeout"] == 15
        return Context()

    monkeypatch.setattr(p.asyncssh, "connect", connect)
    result = await p.fetch_identity(
        SimpleNamespace(adapter="ios", management_ip="192.0.2.1", config_port=2222, ssh_trust_host_key=trust),
        {"username": "fixture", "password": "fixture-secret"},
    )
    assert result == {"vendor": "Cisco", "model": "C9300-48P", "kind": "switch"}


@pytest.mark.parametrize("response_kind", ["json", "redirect", "oversize"])
async def test_rest_identity_has_separate_endpoint_bounded_response_and_no_redirects(
    monkeypatch, response_kind
):
    import httpx

    def respond(request):
        assert str(request.url) == "https://[2001:db8::1]:8443/api/device-info"
        assert request.headers["authorization"] == "Bearer fixture-token"
        if response_kind == "redirect":
            return httpx.Response(302, headers={"location": "https://outside.example/"})
        if response_kind == "oversize":
            return httpx.Response(200, content=b"x" * (256 * 1024 + 1))
        return httpx.Response(
            200, json={"vendor": "Acme", "model": "X1", "device_type": "router", "token": "MUST-HIDE"}
        )

    client = httpx.AsyncClient

    def build_client(**kwargs):
        assert kwargs.get("verify", True) is True
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(p.httpx, "AsyncClient", build_client)
    device = SimpleNamespace(
        adapter="rest", management_ip="2001:db8::1", config_port=8443, identity_path="/api/device-info"
    )
    if response_kind == "json":
        assert await p.fetch_identity(device, {"token": "fixture-token"}) == {
            "vendor": "Acme",
            "model": "X1",
            "kind": "router",
        }
    else:
        with pytest.raises(httpx.HTTPStatusError if response_kind == "redirect" else p.NetworkError):
            await p.fetch_identity(device, {"token": "fixture-token"})


async def test_unsupported_or_failed_neighbor_walks_are_not_complete(monkeypatch):
    from pysnmp.proto.rfc1905 import NoSuchObject

    monkeypatch.setattr(p, "SnmpEngine", Engine)
    monkeypatch.setattr(p, "UdpTransportTarget", Transport)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)

    async def get(*args, **kwargs):
        return None, 0, 0, list(zip(p.SYSTEM.values(), ["switch", "1.3.6.1.4.1", 1000, "core"]))

    async def walk(engine, auth, target, context, oid, **kwargs):
        if oid == p.TABLES["lldp_name"]:
            yield None, 0, 0, [(oid + ".0", NoSuchObject())]
        elif oid == p.TABLES["cdp_name"]:
            yield "timeout", 0, 0, []
        elif oid in (p.TABLES["if_name"], p.TABLES["if_descr"]):
            yield None, 0, 0, [(oid + ".1", "port-1")]

    monkeypatch.setattr(p, "get_cmd", get)
    monkeypatch.setattr(p, "walk_cmd", walk)
    result = await p.SNMPCollector().collect(
        "192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"}
    )
    assert result["neighbors"] == []
    assert result["neighbor_protocols_complete"] == []
    assert set(result["unsupported"]) == {"lldp_name", "cdp_name"}
