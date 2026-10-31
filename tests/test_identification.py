import pytest
from netrix import models as m
from netrix.discovery.identification import normalize, rest_identity, snmp_identity, ssh_identity
from netrix.discovery.protocols import NetworkError
from netrix.worker import claim, execute
from sqlalchemy import select


@pytest.mark.parametrize(
    "adapter,output,expected",
    [
        (
            "ios",
            "Cisco IOS XE Software\nModel Number : C9300-48P\n",
            {"vendor": "Cisco", "model": "C9300-48P", "kind": "switch"},
        ),
        (
            "ios",
            "Cisco IOS Software\ncisco ISR4451-X/K9 (1RU) processor with memory\n",
            {"vendor": "Cisco", "model": "ISR4451-X/K9", "kind": "router"},
        ),
        (
            "junos",
            "Hostname: edge\nModel: mx480\nJunos: 24.4R1\n",
            {"vendor": "Juniper", "model": "mx480", "kind": "router"},
        ),
        (
            "junos",
            "Model: srx1600\nJunos: 24.2\n",
            {"vendor": "Juniper", "model": "srx1600", "kind": "firewall"},
        ),
        (
            "fortios",
            "Version: FortiGate-100F v7.4.0,build1\n",
            {"vendor": "Fortinet", "model": "FortiGate-100F", "kind": "firewall"},
        ),
        (
            "linux",
            "NETRIX_VENDOR=Dell Inc.\nNETRIX_MODEL=PowerEdge R750\nNETRIX_CHASSIS=23\n",
            {"vendor": "Dell Inc.", "model": "PowerEdge R750", "kind": "server"},
        ),
        (
            "linux",
            "Linux router\nNETRIX_VENDOR=To Be Filled By O.E.M.\nNETRIX_MODEL=System Product Name\n",
            {},
        ),
        ("ios", "% Invalid command", {}),
        ("fortios", "Permission denied", {}),
    ],
)
def test_ssh_identity_comes_from_response_not_adapter(adapter, output, expected):
    assert ssh_identity(adapter, output) == expected


def test_snmp_uses_chassis_not_transceiver_and_preserves_ambiguity():
    system = {"sys_object_id": "1.3.6.1.4.1.9.1.1", "sys_description": "Cisco IOS software"}
    tables = {
        "entity_class": {"1": "3", "2": "9"},
        "entity_vendor": {"1": "Cisco", "2": "Module vendor"},
        "entity_model": {"1": "C9300-48P", "2": "SFP-10G"},
    }
    assert snmp_identity(system, tables) == {"vendor": "Cisco", "model": "C9300-48P", "kind": "switch"}
    tables["entity_class"]["3"] = "3"
    tables["entity_model"]["3"] = "C9200-24P"
    assert snmp_identity(system, tables) == {"vendor": "Cisco"}
    assert snmp_identity({"sys_object_id": "1.3.6.1.4.1.900.1", "sys_description": "Linux"}, {}) == {}
    assert ssh_identity("ios", "Cisco IOS XE\nModel Number: C9300-48P\nModel Number: C9200-24P\n") == {
        "vendor": "Cisco"
    }


def test_rest_only_accepts_explicit_nonempty_inventory_fields():
    assert rest_identity(
        {"data": {"manufacturer": "Acme", "model_name": "X42", "device_type": "router", "password": "HIDDEN"}}
    ) == {"vendor": "Acme", "model": "X42", "kind": "router"}
    assert rest_identity({"vendor": "unknown", "model": "", "type": "unknown"}) == {}
    assert rest_identity([{"model": "ambiguous"}]) == {}
    assert normalize({"vendor": "a" * 81, "model": "bad\nvalue", "kind": None}) == {}
    assert normalize({"kind": "other"}) == {}


def test_identity_job_is_documented_in_api_schema(client):
    schema = client.get("/api/v1/openapi.json").json()
    assert "identify" in schema["components"]["schemas"]["JobInput"]["properties"]["kind"]["enum"]


def create_device(client, inventory, **updates):
    payload = {
        "name": "Managed name",
        "management_ip": "192.0.2.1",
        "vrf_id": inventory["vrf"]["id"],
        "vendor": "Manual vendor",
        "model": "Manual model",
        "kind": "router",
        "snmp_credential_id": inventory["credential"]["id"],
        **updates,
    }
    response = client.post("/api/v1/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


class IdentityCollector:
    def __init__(self, values=None, fail=False):
        self.values = values or {}
        self.fail = fail
        self.calls = []

    async def collect(self, host, port, secret):
        self.calls.append((host, port))
        if self.fail:
            raise NetworkError("fixture-secret must never be exposed")
        return {"identity": self.values}


@pytest.mark.parametrize("assignment", ["create", "edit", "bulk"])
async def test_custom_type_survives_identification(admin_client, inventory, env, assignment):
    c = admin_client
    custom = c.post("/api/v1/device-types", json={"name": "Backbone"}).json()
    device, payload = create_device(c, inventory, kind=custom["code"] if assignment == "create" else "switch")
    if assignment == "edit":
        payload["kind"] = custom["code"]
        assert c.put("/api/v1/devices/" + device["id"], json=payload).status_code == 200
    elif assignment == "bulk":
        assert (
            c.post(
                "/api/v1/inventory/devices/bulk",
                json={"ids": [device["id"]], "action": "update", "changes": {"kind": custom["code"]}},
            ).status_code
            == 200
        )
    for kind in ("identify",):
        job = c.post("/api/v1/jobs", json={"kind": kind, "target_id": device["id"]}).json()
        assert claim() == job["id"]
        await execute(job["id"], IdentityCollector({"vendor": "HP", "model": "J9851A", "kind": "switch"}))
        current = c.get("/api/v1/devices/" + device["id"]).json()
        assert (current["kind"], current["kind_name"], current["vendor"], current["model"]) == (
            custom["code"],
            "Backbone",
            "HP",
            "J9851A",
        )
        with env() as db:
            events = db.scalars(
                select(m.Event).where(
                    m.Event.device_id == device["id"], m.Event.kind == "device_identity_change"
                )
            )
            assert all("kind" not in event.details["changes"] for event in events)
            observation = db.scalar(select(m.Observation).where(m.Observation.job_id == job["id"]))
            assert observation.evidence["identity"]["kind"] == "switch"


async def test_custom_type_set_while_device_read_is_in_progress_is_preserved(admin_client, inventory, env):
    custom = admin_client.post("/api/v1/device-types", json={"name": "Controller"}).json()
    device, _ = create_device(admin_client, inventory)

    class ChangedCollector(IdentityCollector):
        async def collect(self, *args):
            with env() as db:
                current = db.get(m.Device, device["id"])
                current.kind = custom["code"]
                db.commit()
            return {"identity": {"vendor": "Aruba", "model": "7205", "kind": "switch"}}

    claim()
    await execute(device["identification"]["job_id"], ChangedCollector())
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert current["kind"] == custom["code"] and current["vendor"] == "Aruba"


async def test_save_queues_identity_and_only_observed_fields_replace_manual(admin_client, inventory, env):
    device, payload = create_device(admin_client, inventory)
    job_id = device["identification"]["job_id"]
    assert device["vendor"] == "Manual vendor" and device["identification"]["status"] == "queued"
    assert (
        admin_client.post("/api/v1/jobs", json={"kind": "identify", "target_id": device["id"]}).json()["id"]
        == job_id
    )
    assert claim() == job_id
    collector = IdentityCollector({"vendor": "Cisco", "model": "", "kind": "unknown"})
    await execute(job_id, collector)
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert (current["vendor"], current["model"], current["kind"], current["name"]) == (
        "Cisco",
        "Manual model",
        "router",
        "Managed name",
    )
    result = admin_client.get("/api/v1/jobs/" + job_id).json()
    assert result["status"] == "partial" and result["result"]["missing_fields"] == ["kind", "model"]
    with env() as db:
        observation = db.scalar(select(m.Observation).where(m.Observation.job_id == job_id))
        assert observation.evidence["identity"] == {"vendor": "Cisco"}
        assert observation.evidence["field_sources"] == {"vendor": "snmpv3"}
        event = db.scalar(select(m.Event).where(m.Event.kind == "device_identity_change"))
        assert event.details["changes"]["vendor"] == {"previous": "Manual vendor", "current": "Cisco"}
    # Editing manual values triggers a new device read; identical saves do not.
    payload["vendor"] = "Cisco"
    unchanged = admin_client.put("/api/v1/devices/" + device["id"], json=payload).json()
    assert "identification" not in unchanged
    payload["model"] = "Updated manual model"
    assert (
        admin_client.put("/api/v1/devices/" + device["id"], json=payload).json()["identification"]["status"]
        == "queued"
    )


@pytest.mark.parametrize("fail", [False, True])
async def test_empty_or_failed_read_never_erases_manual_values(admin_client, inventory, fail):
    device, _ = create_device(admin_client, inventory)
    job_id = device["identification"]["job_id"]
    claim()
    await execute(job_id, IdentityCollector(fail=fail))
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert (current["vendor"], current["model"], current["kind"]) == (
        "Manual vendor",
        "Manual model",
        "router",
    )
    assert current["last_seen_at"] is None
    result = admin_client.get("/api/v1/jobs/" + job_id).json()
    assert result["status"] == ("queued" if fail else "failed")
    for resource in ("jobs", "observations", "events", "audit"):
        assert "fixture-secret" not in admin_client.get("/api/v1/" + resource).text


@pytest.mark.parametrize("protocol", ["ssh", "rest"])
async def test_connection_profile_fallback_completes_metadata(admin_client, inventory, monkeypatch, protocol):
    credential = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "Identity profile",
            "protocol": protocol,
            "secret": {"username": "fixture", "password": "fixture-password", "token": "fixture-token"},
        },
    ).json()
    device, _ = create_device(
        admin_client,
        inventory,
        config_credential_id=credential["id"],
        adapter="rest" if protocol == "rest" else "junos",
    )

    async def read(device, secret):
        assert secret["token" if protocol == "rest" else "password"].startswith("fixture-")
        return {"vendor": "Juniper", "model": "srx1600", "kind": "firewall"}

    monkeypatch.setattr("netrix.worker.fetch_identity", read)
    claim()
    await execute(device["identification"]["job_id"], IdentityCollector(fail=True))
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert (current["vendor"], current["model"], current["kind"]) == ("Juniper", "srx1600", "firewall")
    job = admin_client.get("/api/v1/jobs/" + device["identification"]["job_id"]).json()
    assert job["status"] == "succeeded" and job["result"]["field_sources"]["model"] == protocol


@pytest.mark.parametrize(
    "updates",
    [{"snmp_credential_id": None}, {"management_ip": "198.51.100.1"}, {"lifecycle_status": "planned"}],
)
def test_unauthorized_or_unconfigured_save_stays_manual(admin_client, inventory, updates):
    device, _ = create_device(admin_client, inventory, **updates)
    assert device["identification"]["status"] == "skipped"
    assert device["vendor"] == "Manual vendor"
    assert admin_client.get("/api/v1/jobs").json()["total"] == 0
    assert (
        admin_client.post("/api/v1/jobs", json={"kind": "identify", "target_id": device["id"]}).status_code
        == 422
    )


async def test_changed_endpoint_during_read_cannot_apply_stale_metadata(admin_client, inventory, env):
    device, _ = create_device(admin_client, inventory)

    class ChangedCollector(IdentityCollector):
        async def collect(self, *args):
            with env() as db:
                current = db.get(m.Device, device["id"])
                current.management_ip = "192.0.2.2"
                db.commit()
            return {"identity": {"vendor": "Wrong endpoint", "model": "X", "kind": "switch"}}

    claim()
    await execute(device["identification"]["job_id"], ChangedCollector())
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert current["vendor"] == "Manual vendor"
    assert admin_client.get("/api/v1/observations").json()["total"] == 0


async def test_identification_refresh_preserves_ports(admin_client, inventory, env):
    device, _ = create_device(admin_client, inventory)
    with env() as db:
        db.add(m.Interface(device_id=device["id"], name="Retained port", oper_status="up", is_managed=True))
        db.commit()
    claim()
    await execute(
        device["identification"]["job_id"],
        IdentityCollector({"vendor": "Cisco", "model": "C9300", "kind": "switch"}),
    )
    assert admin_client.get("/api/v1/interfaces").json()["items"][0]["oper_status"] == "up"
    job = admin_client.post("/api/v1/jobs", json={"kind": "identify", "target_id": device["id"]}).json()
    claim()
    await execute(job["id"], IdentityCollector({"vendor": "Juniper", "model": "mx480", "kind": "router"}))
    assert admin_client.get("/api/v1/devices/" + device["id"]).json()["model"] == "mx480"


async def test_identity_job_redelivery_does_not_duplicate_observations_or_events(admin_client, inventory):
    device, _ = create_device(admin_client, inventory)
    job_id = device["identification"]["job_id"]
    claim()
    collector = IdentityCollector({"vendor": "Cisco", "model": "C9300", "kind": "switch"})
    await execute(job_id, collector)
    await execute(job_id, collector)
    assert len(collector.calls) == 1
    assert admin_client.get("/api/v1/observations").json()["total"] == 1
    assert admin_client.get("/api/v1/events").json()["total"] == 1


async def test_identity_cancellation_during_read_preserves_manual_values(admin_client, inventory):
    device, _ = create_device(admin_client, inventory)
    job_id = device["identification"]["job_id"]

    class CancelledCollector(IdentityCollector):
        async def collect(self, *args):
            assert admin_client.post("/api/v1/jobs/" + job_id + "/cancel").status_code == 200
            return {"identity": {"vendor": "Cisco", "model": "C9300", "kind": "switch"}}

    claim()
    await execute(job_id, CancelledCollector())
    assert admin_client.get("/api/v1/jobs/" + job_id).json()["status"] == "cancelled"
    assert admin_client.get("/api/v1/devices/" + device["id"]).json()["vendor"] == "Manual vendor"
    assert admin_client.get("/api/v1/observations").json()["total"] == 0
