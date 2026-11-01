import json

import pytest
from netrix import models as m
from netrix import worker
from netrix.discovery.identification import normalize, snmp_identity, ssh_identity
from test_aruba_adapters import Connection, Shell
from test_identification import IdentityCollector, create_device


@pytest.mark.parametrize(
    "adapter,text,version",
    [
        (
            "aruba_5400",
            "Image stamp: /build/\n Nov 01 2026\n KB.16.11.0032\nBoot ROM Version: KB.16.01.0009",
            "KB.16.11.0032",
        ),
        ("aruba_2900", "Software revision : WC.16.11.0021\nROM Version : WC.16.01.0001", "WC.16.11.0021"),
        (
            "aruba_6100",
            "ArubaOS-CX\nVersion : PL.10.13.1050\nService OS Version : PL.01.14.0002\nBIOS Version : PL.02.0001",
            "PL.10.13.1050",
        ),
        ("aruba_7200", "ArubaOS (MODEL: Aruba7210), Version 8.10.0.14", "8.10.0.14"),
        ("ios", "Cisco IOS XE Software, Version 17.09.04a\nROM: IOS-XE ROMMON", "17.09.04a"),
        ("ios", "Cisco IOS Software, Version 15.2(7)E9, RELEASE SOFTWARE", "15.2(7)E9"),
        ("junos", "Model: ex4300\nJunos: 23.4R2-S3.9", "23.4R2-S3.9"),
        (
            "hp_1950",
            "HPE Comware Software, Version 7.1.070, Release 3506P11\nBootWare Version: 123",
            "7.1.070 Release 3506P11",
        ),
        ("fortios", "Version: FortiGate-600F v7.4.5,build2702,240911 (GA)", "7.4.5 build2702"),
    ],
)
def test_running_software_is_distinct_from_boot_rom(adapter, text, version):
    assert ssh_identity(adapter, text)["software_version"] == version


def test_snmp_prefers_chassis_software_revision_not_module_or_firmware():
    tables = {
        "entity_class": {"1": "3", "2": "9"},
        "entity_software": {"1": "KB.16.11.0032", "2": "999.1"},
        "entity_firmware": {"1": "KB.16.01.0009"},
    }
    assert snmp_identity({}, tables)["software_version"] == "KB.16.11.0032"
    tables["entity_class"]["3"] = "3"
    tables["entity_software"]["3"] = "KB.16.11.0021"
    assert "software_version" not in snmp_identity({}, tables)
    assert (
        snmp_identity(
            {"sys_description": "HP J9851A Switch 5412Rzl2, revision KB.16.11.0032, ROM KB.16.01.0009"}, {}
        )["software_version"]
        == "KB.16.11.0032"
    )
    assert "software_version" not in snmp_identity({"sys_description": "Boot ROM Version: KB.16.01.0009"}, {})


@pytest.mark.parametrize("value", ["unknown", "", "password=secret", "10.1\nsecret", "a" * 121, None])
def test_invalid_or_missing_versions_are_never_invented(value):
    assert "software_version" not in normalize({"software_version": value})


async def test_aoss_reads_software_after_modules_in_same_shell():
    from netrix.discovery.aruba import read_aruba

    shell = Shell(
        {
            "no page": "",
            "show modules": "Chassis: HP 5412Rzl2 J9851A",
            "show version": "Image stamp:\n KB.16.11.0032\nBoot ROM Version: KB.16.01.0009",
        }
    )
    fields = ssh_identity("aruba_5400", await read_aruba(Connection(shell), "aruba_5400"))
    assert fields["software_version"] == "KB.16.11.0032" and fields["model"] == "HP 5412Rzl2 J9851A"
    assert shell.commands == ["no page\n", "show modules\n", "show version\n"] and shell.closed


async def test_version_falls_back_to_ssh_when_snmp_has_complete_identity(
    admin_client, inventory, env, monkeypatch
):
    profile = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "Version SSH",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-secret"},
        },
    ).json()
    device, _ = create_device(admin_client, inventory, config_credential_id=profile["id"])
    calls = []

    async def ssh(device, secret):
        calls.append(device.id)
        return {"software_version": "KB.16.11.0032"}

    monkeypatch.setattr(worker, "fetch_identity", ssh)
    job = admin_client.post("/api/v1/jobs", json={"kind": "identify", "target_id": device["id"]}).json()
    assert worker.claim() == job["id"]
    await worker.execute(job["id"], IdentityCollector({"vendor": "HP", "model": "J9851A", "kind": "switch"}))
    assert calls == [device["id"]]
    assert admin_client.get("/api/v1/devices/" + device["id"]).json()["software_version"] == "KB.16.11.0032"
    result = admin_client.get("/api/v1/inventory/devices", params={"q": "KB.16.11.0032"}).json()
    assert result["total"] == 1 and result["items"][0]["software_version"] == "KB.16.11.0032"
    assert {"key": "software_version", "label": "Versiyon"} in result["columns"]
    assert "fixture-secret" not in json.dumps(result)
    with env() as db:
        assert db.get(m.Device, device["id"]).software_version == "KB.16.11.0032"


def test_failed_read_preserves_previous_version(env, inventory):
    from netrix.inventory.identity import apply_identity

    with env() as db:
        device = m.Device(
            name="Known",
            management_ip="192.0.2.1",
            vrf_id=inventory["vrf"]["id"],
            software_version="KB.16.11.0032",
        )
        db.add(device)
        db.flush()
        apply_identity(db, device, {"software_version": "unknown"}, "fixture", "snmpv3")
        db.commit()
        assert device.software_version == "KB.16.11.0032"
