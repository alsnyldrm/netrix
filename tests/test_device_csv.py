import csv
import io

import pytest
from fastapi import HTTPException
from netrix import models as m
from netrix import services as svc
from netrix.inventory.csv_transfer import FIELDS
from netrix.inventory.csv_transfer import render as render_csv
from sqlalchemy import func, select

pytestmark = pytest.mark.usefixtures("transfer_profiles")


def render(rows):
    return render_csv(
        [
            {
                "snmp_credential_id": "SNMP-Profil-01",
                "config_credential_id": "SSH-Profil-01",
                "ssh_trust_host_key": False,
                **row,
            }
            for row in rows
        ]
    )


BASE = "/api/v1/inventory/devices/csv"


def csv_rows(response):
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_preview_has_no_writes_then_import_queues_only_on_commit(admin_client, inventory, env):
    content = render(
        [
            {
                "name": "İstanbul, omurga",
                "management_ip": "192.0.2.1",
                "vrf_id": "Global",
                "kind": "Switch",
                "monitoring_enabled": "evet",
                "snmp_credential_id": "Test SNMP",
            }
        ]
    )
    with env() as db:
        initial_version = db.get(m.VRF, inventory["vrf"]["id"]).lock_version
    report = admin_client.post(BASE + "/import", json={"content": content}).json()
    assert report["valid"] == 1 and not report["errors"] and not report["imported"]
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 0
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert db.get(m.VRF, inventory["vrf"]["id"]).lock_version == initial_version
    result = admin_client.post(BASE + "/import", json={"content": content, "apply": True})
    assert result.status_code == 200 and result.json()["imported"] == 1
    with env() as db:
        device = db.scalar(select(m.Device))
        assert device.name == "İstanbul, omurga" and device.monitoring_enabled
        assert device.snmp_credential_id == inventory["credential"]["id"]
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "identify")) == 1
    result = admin_client.post(BASE + "/import", json={"content": content, "apply": True}).json()
    assert result["imported"] == 0 and result["errors"]


def test_export_is_selected_only_masks_every_secret_and_round_trips(
    admin_client, inventory, env, monkeypatch
):
    c = admin_client
    ssh = c.post(
        "/api/v1/credentials",
        json={
            "name": "SSH",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "PASSWORD-MUST-NOT-LEAK"},
        },
    ).json()
    rest = c.post(
        "/api/v1/credentials",
        json={"name": "API", "protocol": "rest", "secret": {"token": "TOKEN-MUST-NOT-LEAK"}},
    ).json()
    ids = []
    with env() as db:
        for i in range(3):
            device = m.Device(
                name="=SUM(1,2)" if i == 0 else f"Device {i}",
                management_ip=f"192.0.2.{i + 1}",
                vrf_id=inventory["vrf"]["id"],
                vendor='İmalatçı, "özel"\nseri',
                adapter="rest" if i == 1 else "ios",
                snmp_credential_id=inventory["credential"]["id"],
                config_credential_id=rest["id"] if i == 1 else ssh["id"],
            )
            db.add(device)
            db.flush()
            ids.append(device.id)
        db.commit()
        originals = {p.id: p.encrypted_secret for p in db.scalars(select(m.Credential))}
    monkeypatch.setattr(
        "netrix.identity.security.decrypt", lambda _: pytest.fail("Export must not decrypt credentials")
    )
    response = c.post(BASE + "/export", json={"ids": ids[:2]})
    assert response.status_code == 200
    assert (
        response.content.startswith(b"\xef\xbb\xbf")
        and "attachment" in response.headers["content-disposition"]
    )
    for secret in (
        "PASSWORD-MUST-NOT-LEAK",
        "TOKEN-MUST-NOT-LEAK",
        "fixture-auth",
        "fixture-priv",
        *originals.values(),
    ):
        assert secret not in response.text
    rows = csv_rows(response)
    assert len(rows) == 2 and rows[0]["Cihaz adı"] == "'=SUM(1,2)"
    assert rows[0]["SSH parolası"] == rows[1]["API token"] == "********"
    assert all(
        row["SNMP kimlik doğrulama anahtarı"] == row["SNMP gizlilik anahtarı"] == "********" for row in rows
    )
    for i, row in enumerate(rows):
        row["Yönetim IP adresi"] = f"192.0.2.{100 + i}"
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0])
    writer.writeheader()
    writer.writerows(rows)
    result = c.post(BASE + "/import", json={"content": output.getvalue(), "apply": True}).json()
    assert result["imported"] == 2, result
    with env() as db:
        copied = db.scalar(select(m.Device).where(m.Device.management_ip == "192.0.2.100"))
        assert copied.name == "=SUM(1,2)" and copied.vendor == 'İmalatçı, "özel"\nseri'
        assert {p.id: p.encrypted_secret for p in db.scalars(select(m.Credential))} == originals


@pytest.mark.parametrize(
    "bad",
    [
        {"management_ip": "not-an-ip"},
        {"vrf_id": "missing"},
        {"monitor_interval": "3"},
        {"snmp_credential_id": ""},
        {"adapter": "rest", "config_credential_id": "Test SNMP"},
        {"ssh_password": "PLAINTEXT-SECRET"},
    ],
)
def test_invalid_rows_block_entire_file_without_echoing_values(admin_client, inventory, env, bad):
    good = {"name": "Good", "management_ip": "192.0.2.10", "vrf_id": "Global"}
    content = render([good, {**good, "name": "Bad", "management_ip": "192.0.2.11", **bad}])
    response = admin_client.post(BASE + "/import", json={"content": content, "apply": True})
    result = response.json()
    assert result["imported"] == 0 and result["errors"][0]["row"] == 3
    assert "PLAINTEXT-SECRET" not in response.text
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 0


def test_duplicate_file_addresses_are_normalized_and_rejected(admin_client, inventory):
    rows = [
        {"name": "IPv6", "management_ip": ip, "vrf_id": "Global"}
        for ip in ("2001:db8::1", "2001:0db8:0:0:0:0:0:1")
    ]
    report = admin_client.post(BASE + "/import", json={"content": render(rows), "apply": True}).json()
    assert not report["imported"] and "birden fazla" in report["errors"][0]["message"]


def test_ambiguous_reference_and_invalid_export_selection(admin_client, inventory, env):
    with env() as db:
        db.add_all([m.Site(name="Campus", code="A"), m.Site(name="Campus", code="B")])
        db.commit()
    content = render(
        [{"name": "Switch", "management_ip": "192.0.2.10", "vrf_id": "Global", "site_id": "Campus"}]
    )
    report = admin_client.post(BASE + "/import", json={"content": content}).json()
    assert report["errors"] and "Lokasyon" in report["errors"][0]["message"]
    assert admin_client.post(BASE + "/export", json={"ids": ["absent"]}).status_code == 404
    assert admin_client.post(BASE + "/export", json={"ids": []}).status_code == 422


def test_apply_failure_rolls_back_devices_jobs_and_audit(admin_client, inventory, env, monkeypatch):
    content = render(
        [
            {
                "name": str(i),
                "management_ip": f"192.0.2.{i}",
                "vrf_id": "Global",
                "snmp_credential_id": "Test SNMP",
            }
            for i in (1, 2)
        ]
    )
    original = svc.save_resource
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise HTTPException(409, "Concurrent change")
        return original(*args, **kwargs)

    monkeypatch.setattr(svc, "save_resource", fail_second)
    assert admin_client.post(BASE + "/import", json={"content": content, "apply": True}).status_code == 409
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 0
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert (
            db.scalar(select(func.count()).select_from(m.Audit).where(m.Audit.entity_type == "devices")) == 0
        )


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_csv_template_and_excel_delimiters(admin_client, delimiter):
    template = admin_client.get(BASE + "/template")
    rows = csv_rows(template)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0], delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    report = admin_client.post(BASE + "/import", json={"content": "\ufeff" + output.getvalue()}).json()
    assert report["valid"] == 1 and not report["errors"]


@pytest.mark.parametrize(
    "content",
    [
        "name,name,vrf_id\na,b,Global",
        "name,management_ip\na,192.0.2.1",
        "unknown,secret\na,b",
        "name,management_ip,vrf_id\na,b",
        "name,management_ip,vrf_id\n",
        "\x00",
    ],
)
def test_malformed_csv_is_rejected(admin_client, content):
    assert admin_client.post(BASE + "/import", json={"content": content}).status_code == 422


def test_limits_and_viewer_permissions(admin_client):
    content = render([{"name": "a", "management_ip": "192.0.2.1", "vrf_id": "Global"}] * 501)
    assert admin_client.post(BASE + "/import", json={"content": content}).status_code == 422
    assert admin_client.post(BASE + "/import", json={"content": "ü" * 600000}).status_code == 413
    admin_client.post(
        "/api/v1/users",
        json={
            "email": "viewer@csv.test",
            "display_name": "Viewer",
            "password": "long-fixture-password",
            "role": "viewer",
        },
    )
    admin_client.post("/api/v1/auth/logout")
    admin_client.post(
        "/api/v1/auth/login", json={"email": "viewer@csv.test", "password": "long-fixture-password"}
    )
    assert admin_client.get(BASE + "/template").status_code == 403
    assert admin_client.post(BASE + "/import", json={"content": content}).status_code == 403
    assert admin_client.post(BASE + "/export", json={"ids": ["absent"]}).status_code == 403


def test_csv_schema_covers_all_device_input_fields():
    from netrix.schemas import DeviceInput

    assert set(FIELDS) == set(DeviceInput.model_fields)


def test_snmpv2c_csv_masks_community_and_uses_existing_profile(admin_client, inventory, env):
    profile = admin_client.post(
        "/api/v1/credentials",
        json={"name": "CSV v2c", "protocol": "snmpv2c", "secret": {"community": "PRIVATE-COMMUNITY"}},
    ).json()
    content = render(
        [
            {
                "name": "SNMPv2c device",
                "management_ip": "192.0.2.50",
                "vrf_id": "Global",
                "snmp_credential_id": profile["id"],
                "snmp_community": "********",
                "monitoring_enabled": "true",
            }
        ]
    )
    result = admin_client.post(BASE + "/import", json={"content": content, "apply": True}).json()
    assert result["imported"] == 1, result
    with env() as db:
        device_id = db.scalar(select(m.Device.id).where(m.Device.management_ip == "192.0.2.50"))
    response = admin_client.post(BASE + "/export", json={"ids": [device_id]})
    row = csv_rows(response)[0]
    assert row["SNMP community"] == "********" and row["SNMP profili"] == "CSV v2c"
    assert row["SNMP kimlik doğrulama anahtarı"] == row["SNMP gizlilik anahtarı"] == ""
    assert "PRIVATE-COMMUNITY" not in response.text
    rejected = admin_client.post(
        BASE + "/import", json={"content": content.replace("********", "PRIVATE-COMMUNITY")}
    )
    assert rejected.json()["errors"] and "PRIVATE-COMMUNITY" not in rejected.text
