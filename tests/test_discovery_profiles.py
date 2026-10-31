"""Ordered profile discovery; all SNMP responses are local fakes."""

from collections import defaultdict

import pytest
from netrix import models as m
from netrix.discovery.protocols import NetworkError
from netrix.schemas import ScopeInput
from netrix.worker import claim, execute
from sqlalchemy import select
from test_engines import FixtureCollector


def scope_payload(inventory, **changes):
    data = {key: inventory["scope"][key] for key in ScopeInput.model_fields}
    data.update(changes)
    return data


def second_profile(client, protocol="snmpv2c"):
    response = client.post(
        "/api/v1/credentials",
        json={
            "name": "Alternate fixture " + protocol,
            "protocol": protocol,
            "secret": {"community": "alternate-fixture"}
            if protocol == "snmpv2c"
            else {"username": "fixture", "password": "fixture-password"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def update(client, inventory, **changes):
    return client.put("/api/v1/scopes/" + inventory["scope"]["id"], json=scope_payload(inventory, **changes))


async def run(client, inventory, collector):
    response = client.post("/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert claim() == job_id
    await execute(job_id, collector)
    return client.get("/api/v1/jobs/" + job_id).json()


def test_multiple_profiles_order_validation_and_legacy(admin_client, inventory, env):
    primary = inventory["credential"]["id"]
    alternate = second_profile(admin_client)
    response = update(admin_client, inventory, credential_ids=[alternate, primary, alternate])
    assert response.status_code == 200, response.text
    assert response.json()["credential_ids"] == [alternate, primary]
    assert response.json()["credential_id"] == alternate
    for ids in ([], ["missing"], [second_profile(admin_client, "ssh")], [primary] * 17):
        assert update(admin_client, inventory, credential_ids=ids).status_code in (404, 422)
    assert admin_client.get("/api/v1/scopes/" + inventory["scope"]["id"]).json()["credential_ids"] == [
        alternate,
        primary,
    ]
    # Both primary and secondary references prevent deleting an in-use secret.
    assert admin_client.delete("/api/v1/credentials/" + primary).status_code == 409
    assert admin_client.delete("/api/v1/credentials/" + alternate).status_code == 409
    legacy = scope_payload(inventory)
    legacy.pop("credential_ids")
    assert admin_client.put("/api/v1/scopes/" + inventory["scope"]["id"], json=legacy).json()[
        "credential_ids"
    ] == [primary]
    with env() as db:
        assert list(db.scalars(select(m.ScopeCredential.credential_id))) == [primary]
    assert admin_client.delete("/api/v1/credentials/" + alternate).status_code == 204
    # Saving configuration never launches a scan.
    assert admin_client.get("/api/v1/jobs").json()["items"] == []


@pytest.mark.parametrize("failure", [NetworkError, TimeoutError, OSError])
async def test_fallback_records_working_profile_and_protocol(admin_client, inventory, failure):
    alternate = second_profile(admin_client)
    assert (
        update(admin_client, inventory, credential_ids=[inventory["credential"]["id"], alternate]).status_code
        == 200
    )

    class Collector(FixtureCollector):
        attempts = defaultdict(list)

        async def collect(self, host, port, secret):
            self.attempts[host].append(secret["protocol"])
            if secret["protocol"] == "snmpv3":
                raise failure("fixture failure")
            return await super().collect(host, port, secret)

    collector = Collector()
    result = await run(admin_client, inventory, collector)
    assert result["status"] == "succeeded", result
    assert result["progress"] == result["total"] == 2
    assert result["result"]["reachable"] == 2
    assert dict(collector.attempts) == {
        "192.0.2.1": ["snmpv3", "snmpv2c"],
        "192.0.2.2": ["snmpv3", "snmpv2c"],
    }
    assert {item["snmp_credential_id"] for item in admin_client.get("/api/v1/devices").json()["items"]} == {
        alternate
    }
    assert {item["source"] for item in admin_client.get("/api/v1/observations").json()["items"]} == {
        "snmpv2c"
    }
    assert "alternate-fixture" not in admin_client.get("/api/v1/audit").text


async def test_first_success_stops_and_all_failures_count_hosts_once(admin_client, inventory):
    alternate = second_profile(admin_client)
    update(admin_client, inventory, credential_ids=[inventory["credential"]["id"], alternate])

    class Collector(FixtureCollector):
        async def collect(self, host, port, secret):
            assert secret["protocol"] == "snmpv3"
            return await super().collect(host, port, secret)

    collector = Collector()
    assert (await run(admin_client, inventory, collector))["result"]["reachable"] == 2
    assert len(collector.calls) == 2

    class Failing:
        calls = []

        async def collect(self, host, port, secret):
            self.calls.append((host, secret["protocol"]))
            raise NetworkError("fixture failure")

    collector = Failing()
    result = await run(admin_client, inventory, collector)
    assert len(collector.calls) == 4
    assert result["progress"] == result["total"] == 2
    assert result["result"]["unresponsive"] == 2


@pytest.mark.parametrize("change", ["cancel", "disable", "remove", "rotate"])
async def test_revocation_during_collection_prevents_persistence(admin_client, inventory, env, change):
    alternate = second_profile(admin_client)
    update(
        admin_client,
        inventory,
        credential_ids=[inventory["credential"]["id"], alternate],
        seeds=["192.0.2.1"],
    )

    class Collector(FixtureCollector):
        async def collect(self, host, port, secret):
            with env() as db:
                if change == "cancel":
                    db.scalar(select(m.Job).where(m.Job.status == "running")).cancel_requested = True
                elif change == "disable":
                    db.get(m.Scope, inventory["scope"]["id"]).enabled = False
                elif change == "rotate":
                    from netrix.core import now

                    db.get(m.Credential, inventory["credential"]["id"]).updated_at = now()
                db.commit()
            if change == "remove":
                assert update(admin_client, inventory, credential_ids=[alternate]).status_code == 200
            return await super().collect(host, port, secret)

    result = await run(admin_client, inventory, Collector())
    assert result["status"] == "cancelled", result
    assert admin_client.get("/api/v1/devices").json()["items"] == []


async def test_cancellation_between_failed_profiles_stops_next_attempt(admin_client, inventory, env):
    alternate = second_profile(admin_client)
    update(
        admin_client,
        inventory,
        credential_ids=[inventory["credential"]["id"], alternate],
        seeds=["192.0.2.1"],
    )

    class Collector:
        calls = 0

        async def collect(self, host, port, secret):
            self.calls += 1
            with env() as db:
                db.scalar(select(m.Job).where(m.Job.status == "running")).cancel_requested = True
                db.commit()
            raise NetworkError("fixture failure")

    collector = Collector()
    assert (await run(admin_client, inventory, collector))["status"] == "cancelled"
    assert collector.calls == 1


def test_institution_location_validation_and_legacy_inference(admin_client, inventory):
    first = admin_client.post("/api/v1/institutions", json={"name": "First", "code": "FIRST"}).json()
    second = admin_client.post("/api/v1/institutions", json={"name": "Second", "code": "SECOND"}).json()
    location_data = {"name": "Campus", "institution_id": first["id"]}
    response = admin_client.post("/api/v1/sites", json=location_data)
    assert response.status_code == 201, response.text
    site = response.json()
    response = update(admin_client, inventory, institution_id=first["id"], site_id=site["id"])
    assert response.status_code == 200, response.text
    assert response.json()["institution_id"] == first["id"]
    assert update(admin_client, inventory, institution_id=second["id"], site_id=site["id"]).status_code == 422
    assert update(admin_client, inventory, institution_id="missing").status_code == 422
    assert (
        admin_client.put(
            "/api/v1/sites/" + site["id"], json={**location_data, "institution_id": second["id"]}
        ).status_code
        == 409
    )
    assert (
        update(admin_client, inventory, institution_id=None, site_id=site["id"]).json()["institution_id"]
        == first["id"]
    )
    response = update(admin_client, inventory, institution_id=second["id"], site_id=None)
    assert response.status_code == 200
    assert response.json()["site_id"] is None
    assert admin_client.delete("/api/v1/institutions/" + second["id"]).status_code == 409


async def test_existing_device_uses_working_profile_without_overwriting_external_assignment(
    admin_client, inventory, env
):
    alternate = second_profile(admin_client)
    update(admin_client, inventory, credential_ids=[inventory["credential"]["id"], alternate])
    assert (await run(admin_client, inventory, FixtureCollector()))["status"] == "succeeded"
    external = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "Separately managed profile",
            "protocol": "snmpv2c",
            "secret": {"community": "external-fixture"},
        },
    ).json()["id"]
    with env() as db:
        device = db.scalar(select(m.Device).where(m.Device.management_ip == "192.0.2.2"))
        device.snmp_credential_id = external
        db.commit()

    class Collector(FixtureCollector):
        async def collect(self, host, port, secret):
            if secret["protocol"] == "snmpv3":
                raise NetworkError("fixture failure")
            return await super().collect(host, port, secret)

    assert (await run(admin_client, inventory, Collector()))["status"] == "succeeded"
    devices = admin_client.get("/api/v1/devices").json()["items"]
    assert {device["management_ip"]: device["snmp_credential_id"] for device in devices} == {
        "192.0.2.1": alternate,
        "192.0.2.2": external,
    }
