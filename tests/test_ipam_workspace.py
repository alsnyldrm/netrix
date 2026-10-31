import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.identity.security import decrypt
from netrix.ipam import adapters, service
from sqlalchemy import func, select


def prefix(client, inventory, cidr="192.0.2.0/30"):
    result = client.post("/api/v1/prefixes", json={"cidr": cidr, "vrf_id": inventory["vrf"]["id"]})
    assert result.status_code == 201, result.text
    return result.json()


def integration(client, p, **changes):
    payload = dict(
        name="VC",
        kind="vcenter",
        host="vc.example.test",
        port=443,
        username="fixture-user",
        password="fixture-secret",
        enabled=True,
        prefix_ids=[p["id"]],
    )
    payload.update(changes)
    result = client.post("/api/v1/integrations", json=payload)
    assert result.status_code == 201, result.text
    assert "fixture-secret" not in result.text and "encrypted_secret" not in result.text
    return result.json()


def test_all_addresses_ipv6_and_managed_metadata(admin_client, inventory):
    c = admin_client
    p = prefix(c, inventory)
    response = c.get(f"/api/v1/ipam/prefixes/{p['id']}/addresses").json()
    assert [r["address"] for r in response["items"]] == ["192.0.2.0", "192.0.2.1", "192.0.2.2", "192.0.2.3"]
    assert response["items"][0]["status"] == "network"
    assert c.get("/api/v1/addresses").json()["total"] == 0
    item = c.post(
        "/api/v1/addresses",
        json=dict(
            address="192.0.2.2",
            prefix_id=p["id"],
            vrf_id=p["vrf_id"],
            operating_system="Debian",
            cabinet="K-01",
            location="Kat 2",
        ),
    ).json()
    assert item["cabinet"] == "K-01"
    p6 = prefix(c, inventory, "2001:db8::/64")
    r = c.get(f"/api/v1/ipam/prefixes/{p6['id']}/addresses?offset=18446744073709551615").json()
    assert r["total"] == "18446744073709551616" and len(r["items"]) == 1
    assert r["items"][0]["address"] == "2001:db8::ffff:ffff:ffff:ffff"
    assert c.get(f"/api/v1/ipam/prefixes/{p6['id']}/addresses?offset=-1").status_code == 422


def test_block_settings_scope_exclusions_and_dedup(admin_client, inventory, env):
    c = admin_client
    p = prefix(c, inventory)
    assert c.post(f"/api/v1/ipam/prefixes/{p['id']}/discover").status_code == 422
    assert c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"ping_enabled": True}).status_code == 422
    assert (
        c.put(
            f"/api/v1/ipam/prefixes/{p['id']}/settings",
            json={
                "scope_id": inventory["scope"]["id"],
                "warning_threshold": 50,
                "ping_enabled": True,
                "discovery_enabled": True,
            },
        ).status_code
        == 200
    )
    with env() as db:
        scope = db.get(m.Scope, inventory["scope"]["id"])
        scope.exclusions = ["192.0.2.2/32"]
        db.commit()
        assert service.targets(db, db.get(m.Prefix, p["id"]), True) == ["192.0.2.1"]
    a = c.post(f"/api/v1/ipam/prefixes/{p['id']}/discover").json()
    b = c.post(f"/api/v1/ipam/prefixes/{p['id']}/discover").json()
    assert a["id"] == b["id"]
    c.post("/api/v1/addresses", json={"address": "192.0.2.1", "prefix_id": p["id"], "vrf_id": p["vrf_id"]})
    assert c.get("/api/v1/prefixes").json()["items"][0]["threshold_exceeded"] is False


@pytest.mark.asyncio
async def test_scan_dns_no_reply_keeps_assignment_and_no_real_network(
    admin_client, inventory, env, monkeypatch
):
    c = admin_client
    p = prefix(c, inventory)
    dns = c.post("/api/v1/dns-servers", json={"name": "Internal", "address": "192.0.2.53"}).json()
    c.put(
        f"/api/v1/ipam/prefixes/{p['id']}/settings",
        json={"scope_id": inventory["scope"]["id"], "dns_server_id": dns["id"]},
    )
    existing = c.post(
        "/api/v1/addresses",
        json={"address": "192.0.2.2", "prefix_id": p["id"], "vrf_id": p["vrf_id"], "status": "reserved"},
    ).json()
    seen = []

    async def ping(address):
        seen.append(address)
        return address.endswith(".1")

    async def dns_query(address, server):
        assert server.id == dns["id"]
        return "server.example.test"

    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns_query)
    job = c.post(f"/api/v1/ipam/prefixes/{p['id']}/discover").json()
    await worker.execute(job["id"])
    result = c.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "succeeded", result
    assert set(seen) == {"192.0.2.1", "192.0.2.2"}
    rows = c.get("/api/v1/addresses").json()["items"]
    assert len(rows) == 2
    found = next(r for r in rows if r["address"] == "192.0.2.1")
    assert found["hostname"] == "server.example.test"
    assert found["managed"]["hostname"] == ""
    assert next(r for r in rows if r["id"] == existing["id"])["status"] == "reserved"
    assert next(r for r in rows if r["id"] == existing["id"])["reachability"] == "no_reply"


@pytest.mark.asyncio
async def test_integration_atomic_scope_manual_preservation_and_idempotency(
    admin_client, inventory, env, monkeypatch
):
    c = admin_client
    p = prefix(c, inventory)
    row = c.post(
        "/api/v1/addresses",
        json={
            "address": "192.0.2.1",
            "prefix_id": p["id"],
            "vrf_id": p["vrf_id"],
            "hostname": "managed",
            "operating_system": "managed-os",
        },
    ).json()
    config = integration(c, p)
    with env() as db:
        stored = db.get(m.Integration, config["id"])
        assert "fixture-secret" not in stored.encrypted_secret
        assert json.loads(decrypt(stored.encrypted_secret))["password"] == "fixture-secret"

    def reader(config, secret):
        assert secret["password"] == "fixture-secret"
        return [
            dict(
                address="192.0.2.1",
                hostname="observed",
                mac_address="00:11:22:33:44:55",
                operating_system="Linux",
                vm_id="vm-1",
                nic_key="4000",
                power_state="poweredOn",
            ),
            dict(address="203.0.113.1", hostname="outside", vm_id="vm-2", nic_key="4000"),
        ]

    monkeypatch.setattr(adapters, "vcenter_records", reader)
    for _ in range(2):
        job = c.post("/api/v1/integrations/" + config["id"] + "/sync").json()
        await worker.execute(job["id"])
        result = c.get("/api/v1/jobs/" + job["id"]).json()
        assert result["status"] == "succeeded", result
        assert result["result"]["outside_selected_prefixes"] == 1
    value = c.get("/api/v1/ipam/addresses/" + row["id"]).json()
    assert value["hostname"] == "managed" and value["operating_system"] == "managed-os"
    assert value["observations"][0]["data"]["hostname"] == "observed"
    assert len(value["integrations"]) == 1
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.IPObservation)) == 1
    assert c.get("/api/v1/addresses").json()["total"] == 1


def test_integration_credentials_edit_and_cross_vrf_rejected(admin_client, inventory, env):
    c = admin_client
    p = prefix(c, inventory)
    config = integration(c, p)
    data = {
        k: config[k]
        for k in ("name", "kind", "host", "port", "enabled", "verify_tls", "prefix_ids", "interval_seconds")
    }
    assert c.put("/api/v1/integrations/" + config["id"], json=data).status_code == 200
    data["host"] = "another.example.test"
    assert c.put("/api/v1/integrations/" + config["id"], json=data).status_code == 422
    data["username"] = "fixture-user"
    data["password"] = "new-secret"
    assert c.put("/api/v1/integrations/" + config["id"], json=data).status_code == 200
    assert (
        c.post(
            "/api/v1/integrations", json={**data, "name": "Bad URL", "host": "https://host/path"}
        ).status_code
        == 422
    )
    vrf = c.post("/api/v1/vrfs", json={"name": "other"}).json()
    p2 = c.post("/api/v1/prefixes", json={"cidr": p["cidr"], "vrf_id": vrf["id"]}).json()
    assert (
        c.post(
            "/api/v1/integrations", json={**data, "name": "Ambiguous", "prefix_ids": [p["id"], p2["id"]]}
        ).status_code
        == 422
    )
    with env() as db:
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    assert c.post("/api/v1/integrations/" + config["id"] + "/sync").status_code == 403
    assert c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={}).status_code == 403


def test_cross_device_mac_correlation_marks_multiple_ports(admin_client, inventory, env):
    c = admin_client
    p = prefix(c, inventory)
    with env() as db:
        prefix_row = db.get(m.Prefix, p["id"])
        row = service.observe(
            db, prefix_row, "192.0.2.1", "inventory", "gateway", {"mac_address": "00:11:22:33:44:55"}
        )
        for n in (1, 2):
            device = m.Device(name=f"switch{n}", management_ip=f"192.0.2.{n}", vrf_id=p["vrf_id"])
            db.add(device)
            db.flush()
            port = m.Interface(device_id=device.id, name="Gi1", if_index=7)
            db.add(port)
            job = m.Job(kind="monitor", target_id=device.id)
            db.add(job)
            db.flush()
            db.add(
                m.Observation(
                    job_id=job.id,
                    device_id=device.id,
                    address=device.management_ip,
                    evidence={
                        "tables": {"fdb_port": {"0.17.34.51.68.85": "3"}, "bridge_ifindex": {"3": "7"}},
                        "neighbors": [],
                    },
                )
            )
        db.commit()
        candidates = service.connection_candidates(db, row)
        assert len(candidates) == 2 and all(r["ambiguous"] for r in candidates)
        assert {r["device_name"] for r in candidates} == {"switch1", "switch2"}
        row_id = row.id
    assert (
        c.post(f"/api/v1/ipam/addresses/{row_id}/live", json={"interface_id": "unrelated"}).status_code == 422
    )


def test_windows_dhcp_parser_mac_and_readonly_commands():
    rows = adapters.dhcp_records(
        b'[{"address":"192.0.2.1","mac_address":"01-00-11-22-33-44-55","hostname":"PC"}]'
    )
    assert rows[0]["mac_address"] == "00:11:22:33:44:55"
    assert rows[0]["reserved"]
    assert "Get-DhcpServerv4Reservation" in adapters.DHCP_SCRIPT
    assert "Set-Dhcp" not in adapters.DHCP_SCRIPT
    assert service.normalized_mac("not-an-ethernet-client-id") == ""


def test_vm_dvswitch_guest_info():
    from pyVmomi import vim

    nic = vim.vm.device.VirtualVmxnet3(
        key=4000,
        macAddress="00:11:22:33:44:55",
        backing=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
            port=vim.dvs.PortConnection(switchUuid="dvs-id", portKey="18")
        ),
    )
    guest = SimpleNamespace(
        hostName="guest",
        guestFullName="Ubuntu",
        net=[
            SimpleNamespace(
                deviceConfigId=4000,
                ipConfig=SimpleNamespace(ipAddress=[SimpleNamespace(ipAddress="192.0.2.1")]),
                macAddress=nic.macAddress,
                network="DV-PG",
            )
        ],
    )
    rows = adapters.vm_records(
        "vm-1", {"guest": guest, "config.hardware.device": [nic], "runtime.powerState": "poweredOn"}
    )
    assert rows[0]["dvport"] == "18" and rows[0]["dvswitch"] == "dvs-id"
    assert rows[0]["operating_system"] == "Ubuntu" and rows[0]["nic_key"] == "4000"


def test_stale_observations_not_presented_as_current(admin_client, inventory, env):
    p = prefix(admin_client, inventory)
    with env() as db:
        row = service.observe(
            db,
            db.get(m.Prefix, p["id"]),
            "192.0.2.1",
            "vcenter",
            "vc",
            {"operating_system": "old", "power_state": "poweredOn"},
        )
        db.scalar(select(m.IPObservation)).observed_at = now() - timedelta(days=2)
        db.commit()
        value = service.enrich(db, [row])[0]
        assert value["stale"] and not value["power_state"] and not value["operating_system"]


@pytest.mark.asyncio
async def test_scan_cancel_does_not_start_ping(admin_client, inventory, env, monkeypatch):
    c = admin_client
    p = prefix(c, inventory)
    c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"scope_id": inventory["scope"]["id"]})
    job = c.post(f"/api/v1/ipam/prefixes/{p['id']}/discover").json()
    c.post("/api/v1/jobs/" + job["id"] + "/cancel")

    async def forbidden(address):
        raise AssertionError("Cancelled job made network request")

    monkeypatch.setattr(adapters, "ping", forbidden)
    await worker.execute(job["id"])
    assert c.get("/api/v1/jobs/" + job["id"]).json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_dhcp_reservation_matches_vcenter_mac_without_guest_ip(
    admin_client, inventory, env, monkeypatch
):
    c = admin_client
    p = prefix(c, inventory)
    vc = integration(c, p)
    dhcp = integration(c, p, name="DHCP", kind="windows_dhcp", port=5986)
    monkeypatch.setattr(
        adapters,
        "windows_dhcp",
        lambda *_: [
            {
                "address": "192.0.2.1",
                "mac_address": "00:11:22:33:44:55",
                "hostname": "reserved-host",
                "reserved": True,
            }
        ],
    )
    monkeypatch.setattr(
        adapters,
        "vcenter_records",
        lambda *_: [
            {
                "address": "",
                "mac_address": "00:11:22:33:44:55",
                "hostname": "guest-host",
                "operating_system": "Windows Server",
                "vm_id": "vm-1",
                "nic_key": "4000",
                "power_state": "poweredOff",
            }
        ],
    )
    task = c.post("/api/v1/integrations/" + dhcp["id"] + "/sync").json()
    await worker.execute(task["id"])
    with env() as db:
        followup = db.scalar(select(m.Job).where(m.Job.target_id == vc["id"]))
        assert followup and followup.status == "queued"
        followup_id = followup.id
    await worker.execute(followup_id)
    result = c.get("/api/v1/addresses").json()["items"]
    assert len(result) == 1 and result[0]["status"] == "reserved"
    assert result[0]["operating_system"] == "Windows Server"
    assert result[0]["power_state"] == "poweredOff"
    assert result[0]["observations"][0]["data"]["matched_by"] == "dhcp_mac"


@pytest.mark.asyncio
async def test_live_vcenter_deduplicates_source_timestamp(admin_client, inventory, env, monkeypatch):
    from netrix.ipam import jobs

    c = admin_client
    p = prefix(c, inventory)
    vc = integration(c, p)
    with env() as db:
        row = service.observe(
            db,
            db.get(m.Prefix, p["id"]),
            "192.0.2.1",
            "vcenter",
            vc["id"],
            {"integration_id": vc["id"], "vm_id": "vm-1", "nic_key": "4000"},
        )
        db.commit()
        row_id = row.id
    task = c.post(f"/api/v1/ipam/addresses/{row_id}/live", json={"integration_id": vc["id"]})
    assert task.status_code == 202, task.text
    assert (
        c.post(f"/api/v1/ipam/addresses/{row_id}/live", json={"integration_id": vc["id"]}).json()["id"]
        == task.json()["id"]
    )
    stamp = now()
    monkeypatch.setattr(
        adapters,
        "vcenter_traffic",
        lambda *_: {"sampled_at": stamp, "interval_seconds": 20, "in_bps": 8000, "out_bps": 4000},
    )

    async def no_wait(*_):
        pass

    monkeypatch.setattr(jobs.asyncio, "sleep", no_wait)
    result = await jobs.live(task.json()["id"], None)
    assert result["samples"] == 1
    samples = c.get(f"/api/v1/ipam/addresses/{row_id}/traffic").json()["items"]
    assert len(samples) == 1 and samples[0]["interval_seconds"] == 20 and samples[0]["in_bps"] == 8000


@pytest.mark.asyncio
async def test_snmp_live_baseline_reset_and_measured_interval(admin_client, inventory, env, monkeypatch):
    from netrix.ipam import jobs

    c = admin_client
    p = prefix(c, inventory)
    with env() as db:
        device = m.Device(
            name="Edge",
            management_ip="192.0.2.2",
            vrf_id=p["vrf_id"],
            snmp_credential_id=inventory["credential"]["id"],
        )
        db.add(device)
        db.flush()
        port = m.Interface(name="Gi1", device_id=device.id, if_index=7, speed_bps=1000000000)
        db.add(port)
        db.flush()
        row = m.IPAddress(address="192.0.2.1", vrf_id=p["vrf_id"], prefix_id=p["id"], interface_id=port.id)
        db.add(row)
        db.commit()
        row_id, port_id = row.id, port.id
    task = c.post(f"/api/v1/ipam/addresses/{row_id}/live", json={"interface_id": port_id})
    assert task.status_code == 202, task.text
    stamp = now()
    n = 0

    class Collector:
        async def interface_counters(self, host, port, secret, index):
            nonlocal n
            assert host == "192.0.2.2" and index == 7
            n += 1
            return dict(
                in_octets=n * 1000,
                out_octets=n * 500,
                uptime_ticks=n * 500,
                discontinuity_ticks=1 if n >= 3 else 0,
            )

    monkeypatch.setattr(jobs, "now", lambda: stamp + timedelta(seconds=n * 5))

    async def no_wait(*_):
        pass

    monkeypatch.setattr(jobs.asyncio, "sleep", no_wait)
    await jobs.live(task.json()["id"], Collector())
    samples = c.get(f"/api/v1/ipam/addresses/{row_id}/traffic").json()["items"]
    assert len(samples) == 12
    assert samples[0]["in_bps"] is None
    assert samples[1]["in_bps"] == 1600
    assert samples[2]["in_bps"] is None
    assert samples[3]["out_bps"] == 800


def test_windows_reader_tls_and_cleanup(monkeypatch):
    import base64

    import winrm

    calls = []

    class Protocol:
        def open_shell(self):
            return "shell"

        def run_command(self, shell, command, args):
            assert command == "powershell.exe"
            script = base64.b64decode(args[-1]).decode("utf-16-le")
            assert script == adapters.DHCP_SCRIPT
            return "command"

        def get_command_output_raw(self, *args):
            return (
                b'[{"address":"192.0.2.1","mac_address":"00-11-22-33-44-55","hostname":"PC"}]',
                b"",
                0,
                True,
            )

        def cleanup_command(self, *args):
            calls.append("cleanup")

        def close_shell(self, *args):
            calls.append("close")

    def session(url, **kwargs):
        assert url == "https://dhcp.example.test:5986/wsman"
        assert kwargs["transport"] == "ntlm" and kwargs["server_cert_validation"] == "validate"
        return SimpleNamespace(protocol=Protocol())

    monkeypatch.setattr(winrm, "Session", session)
    result = adapters.windows_dhcp(
        SimpleNamespace(host="dhcp.example.test", port=5986, verify_tls=True),
        {"username": "fixture", "password": "fixture-secret"},
    )
    assert result[0]["mac_address"] == "00:11:22:33:44:55" and calls == ["cleanup", "close"]


def test_vcenter_performance_uses_provider_interval_and_bytes_to_bits(monkeypatch):
    from pyVim import connect
    from pyVmomi import vim

    stamp = now()

    class Perf:
        perfCounter = [
            SimpleNamespace(
                nameInfo=SimpleNamespace(key=name),
                groupInfo=SimpleNamespace(key="net"),
                rollupType="average",
                unitInfo=SimpleNamespace(key="kiloBytesPerSecond"),
                key=key,
            )
            for name, key in [("received", 10), ("transmitted", 11)]
        ]

        def QueryPerfProviderSummary(self, entity):
            return SimpleNamespace(refreshRate=20)

        def QueryPerf(self, querySpec):
            spec = querySpec[0]
            assert spec.intervalId == 20 and spec.maxSample == 1
            assert all(v.instance == "4000" for v in spec.metricId)
            return [
                SimpleNamespace(
                    sampleInfo=[SimpleNamespace(timestamp=stamp)],
                    value=[
                        SimpleNamespace(id=SimpleNamespace(counterId=10), value=[10]),
                        SimpleNamespace(id=SimpleNamespace(counterId=11), value=[-1]),
                    ],
                )
            ]

    monkeypatch.setattr(
        adapters,
        "connect_vcenter",
        lambda *_: SimpleNamespace(_stub=None, RetrieveContent=lambda: SimpleNamespace(perfManager=Perf())),
    )
    monkeypatch.setattr(connect, "Disconnect", lambda *_: None)
    # vim.VirtualMachine accepts a null stub for a property-free query fixture.
    assert vim.VirtualMachine("vm-1", None)._moId == "vm-1"
    result = adapters.vcenter_traffic(None, None, "vm-1", "4000")
    assert result["in_bps"] == 81920 and result["out_bps"] is None and result["sampled_at"] == stamp


@pytest.mark.parametrize("kind,port", [("vcenter", 443), ("windows_dhcp", 5986)])
def test_integration_settings_keep_encrypted_credentials(admin_client, inventory, env, kind, port):
    p = prefix(admin_client, inventory)
    config = integration(admin_client, p, kind=kind, port=port)
    with env() as db:
        original = db.get(m.Integration, config["id"]).encrypted_secret
    payload = {
        key: config[key]
        for key in ("name", "kind", "host", "port", "enabled", "verify_tls", "prefix_ids", "interval_seconds")
    }
    payload.update(name="Updated integration", interval_seconds=120, username="", password="")
    url = "/api/v1/integrations/" + config["id"]
    response = admin_client.put(url, json=payload)
    assert response.status_code == 200, response.text
    with env() as db:
        stored = db.get(m.Integration, config["id"])
        assert stored.encrypted_secret == original
        assert stored.interval_seconds == 120
    # A partial credential replacement must not erase either saved value.
    assert admin_client.put(url, json={**payload, "username": "replacement"}).status_code == 422
    with env() as db:
        assert db.get(m.Integration, config["id"]).encrypted_secret == original
    response = admin_client.put(
        url, json={**payload, "username": "replacement", "password": "rotated-secret"}
    )
    assert response.status_code == 200, response.text
    with env() as db:
        changed = db.get(m.Integration, config["id"]).encrypted_secret
        assert changed != original
        assert json.loads(decrypt(changed)) == {"username": "replacement", "password": "rotated-secret"}
    for path in (url, "/api/v1/integrations", "/api/v1/audit"):
        response = admin_client.get(path)
        assert response.status_code == 200
        assert all(
            value not in response.text for value in ("rotated-secret", "fixture-secret", "encrypted_secret")
        )
