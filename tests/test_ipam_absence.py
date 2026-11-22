from copy import deepcopy

import pytest
from netrix import models as m
from netrix import worker
from netrix.ipam import adapters, service
from netrix.sources.network import read
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network


@pytest.mark.parametrize(
    "scenario", ["dhcp_port", "absent", "dns_failure", "ping_reply", "partial_fdb", "managed", "fdb_only"]
)
async def test_scheduled_gateway_gap_checks_inventory_before_deciding(
    admin_client, network, monkeypatch, scenario
):
    sf, vid, rid, devices = network
    target = "192.0.2.10"
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        vlan.cidr = "192.0.2.8/30"
        gateway = read(
            db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == devices[0]))
        )
        gateway = deepcopy(gateway)
        gateway.pop("_bindings", None)
        gateway["tables"]["arp_mac"] = {}
        gateway["tables"]["ndp_mac"] = {}
        gateway["tables"]["arp_type"] = {}
        gateway["unsupported"] = []
        gateway.pop("table_reads", None)
        for device in devices[1:]:
            state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == device))
            state.neighbors_at = state.observed_at
            if scenario not in ("dhcp_port", "fdb_only"):
                state.mac_entries = []
            if scenario == "partial_fdb":
                state.fdb_complete = False
        if scenario == "managed":
            db.add(m.Audit(action="create", entity_type="addresses", entity_id=rid, summary="Elle eklendi"))
        if scenario == "dhcp_port":
            from netrix.identity.security import encrypt

            db.add(
                m.Integration(
                    kind="windows_dhcp",
                    name="DHCP",
                    host="example.invalid",
                    port=5986,
                    encrypted_secret=encrypt("{}"),
                    enabled=True,
                )
            )
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "schedule"})
        db.add(job)
        db.commit()
        jid = job.id

    calls = []

    class Collector:
        async def ipam(self, host, *_):
            assert host == "198.51.100.1"
            assert target in calls, "Gateway ARP collected before the target was probed"
            return deepcopy(gateway)

    async def ping(address):
        calls.append(address)
        return scenario == "ping_reply" and address == target

    async def dns(address, _):
        if scenario == "dns_failure" and address == target:
            from netrix.discovery.protocols import NetworkError

            raise NetworkError("test DNS timeout")
        return ""

    def dhcp(*_, **__):
        return [dict(address=target, mac_address=MAC, hostname="reservation.example", reserved=True)]

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    monkeypatch.setattr(adapters, "windows_dhcp", dhcp)
    await worker.execute(jid, Collector())
    with sf() as db:
        job = db.get(m.Job, jid)
        assert job.status in ("succeeded", "partial"), job.error
        row = db.get(m.IPAddress, rid)
        assert bool(row) == (scenario != "absent")
        assert job.result["removed"] == int(scenario == "absent")
        if scenario == "dhcp_port":
            item = service.enrich(db, [row])[0]
            assert item["scan_status"] == "success", item["scan_result"]
            assert item["hostname"] == "reservation.example"
            assert item["connected_device"] == "Access"
            assert item["connected_port"] == "Gi1/0/1"
            assert item["field_sources"]["mac_address"] == "windows_dhcp"
            steps = {s["source"]: s["status"] for s in item["scan_result"]["steps"]}
            assert steps == {
                "gateway": "missing",
                "vmware": "missing",
                "dhcp": "with_data",
                "backbone": "with_data",
                "dns": "missing",
            }
        if scenario == "dns_failure":
            item = service.enrich(db, [row])[0]
            assert any(i["source"] == "dns" for i in item["scan_result"]["issues"])
            assert not any(i["code"] == "missing_hostname" for i in item["scan_result"]["issues"])
            assert any(s["source"] == "dns" and s["status"] == "error" for s in item["scan_result"]["steps"])


@pytest.mark.parametrize("error_name", ["NXDOMAIN", "NoAnswer"])
async def test_ptr_negative_answer_does_not_retry(monkeypatch, error_name):
    import dns.asyncresolver
    import dns.resolver

    attempts = []

    async def resolve(_resolver, _name, _kind, *, tcp=False, lifetime=None):
        attempts.append(tcp)
        raise getattr(dns.resolver, error_name)()

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", resolve)
    assert await adapters.reverse_dns("192.0.2.10", None) == ""
    assert attempts == [False]


@pytest.mark.parametrize("first_error", ["LifetimeTimeout", "NoNameservers"])
@pytest.mark.parametrize("tcp_succeeds", [True, False])
async def test_ptr_retries_transient_failure_on_the_same_server(monkeypatch, first_error, tcp_succeeds):
    from types import SimpleNamespace

    import dns.asyncresolver
    import dns.resolver

    attempts = []
    server = SimpleNamespace(address="192.0.2.53", port=5353)

    async def resolve(resolver, name, kind, *, tcp=False, lifetime=None):
        assert str(name) == "10.2.0.192.in-addr.arpa."
        assert kind == "PTR"
        assert resolver.nameservers == [server.address]
        assert resolver.port == server.port
        attempts.append((tcp, resolver.lifetime if lifetime is None else lifetime))
        if not tcp:
            raise getattr(dns.resolver, first_error)()
        if not tcp_succeeds:
            raise dns.resolver.LifetimeTimeout()
        return ["host.example.test."]

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", resolve)
    if tcp_succeeds:
        assert await adapters.reverse_dns("192.0.2.10", server) == "host.example.test"
    else:
        with pytest.raises(TimeoutError):
            await adapters.reverse_dns("192.0.2.10", server)
    assert [tcp for tcp, _ in attempts] == [False, True]
    assert sum(lifetime for _, lifetime in attempts) <= 2
