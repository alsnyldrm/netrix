"""SNMPv2c vault, secret rotation and worker flows without network access."""

import pytest
from netrix import models as m
from netrix.identity.security import secret_data
from netrix.schemas import ScopeInput
from netrix.worker import claim, execute
from test_engines import FixtureCollector


def create_profile(client, community=" fixture-community "):
    return client.post(
        "/api/v1/credentials",
        json={
            "name": "SNMPv2c fixture",
            "protocol": "snmpv2c",
            "secret": {"community": community},
        },
    )


@pytest.mark.parametrize("community", ["", "   ", "x" * 256])
def test_invalid_community_is_rejected(admin_client, community):
    response = create_profile(admin_client, community)
    assert response.status_code == 422
    if community.strip():
        assert community not in response.text


def test_community_encryption_rotation_and_redaction(admin_client, env):
    response = create_profile(admin_client)
    assert response.status_code == 201, response.text
    profile_id = response.json()["id"]
    with env() as db:
        profile = db.get(m.Credential, profile_id)
        ciphertext = profile.encrypted_secret
        assert "fixture-community" not in ciphertext
        assert secret_data(profile)["community"] == " fixture-community "
    response = admin_client.put(
        "/api/v1/credentials/" + profile_id,
        json={
            "name": "SNMPv2c fixture",
            "protocol": "snmpv2c",
            "secret": {"community": "rotated-community"},
        },
    )
    assert response.status_code == 200
    with env() as db:
        profile = db.get(m.Credential, profile_id)
        assert secret_data(profile)["community"] == "rotated-community"
        assert ciphertext != profile.encrypted_secret
    for path in ("/credentials", "/credentials/" + profile_id, "/audit"):
        text = admin_client.get("/api/v1" + path).text
        assert all(
            secret not in text for secret in ("fixture-community", "rotated-community", "encrypted_secret")
        )
    assert (
        admin_client.put(
            "/api/v1/credentials/" + profile_id,
            json={
                "name": "SNMPv2c fixture",
                "protocol": "ssh",
                "secret": {"username": "fixture", "password": "fixture"},
            },
        ).status_code
        == 409
    )


async def test_v2c_discovery_monitor_identity_and_probe(admin_client, inventory):
    response = create_profile(admin_client)
    assert response.status_code == 201
    profile_id = response.json()["id"]
    scope = {key: inventory["scope"][key] for key in ScopeInput.model_fields}
    scope["credential_id"] = profile_id
    assert admin_client.put("/api/v1/scopes/" + inventory["scope"]["id"], json=scope).status_code == 200

    class Collector(FixtureCollector):
        async def collect(self, host, port, secret):
            assert secret["protocol"] == "snmpv2c"
            assert secret["community"] == " fixture-community "
            data = await super().collect(host, port, secret)
            data["identity"] = {"vendor": "Fixture", "model": "Switch", "kind": "switch"}
            return data

        async def probe(self, host, port, secret):
            assert secret["protocol"] == "snmpv2c" and port == 161
            assert secret["community"] == " fixture-community "

    collector = Collector()

    async def run(kind, target):
        response = admin_client.post("/api/v1/jobs", json={"kind": kind, "target_id": target})
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        assert claim() == job_id
        await execute(job_id, collector)
        result = admin_client.get("/api/v1/jobs/" + job_id).json()
        assert result["status"] == "succeeded", result
        return result

    await run("discovery", inventory["scope"]["id"])
    device = admin_client.get("/api/v1/devices").json()["items"][0]
    assert device["snmp_credential_id"] == profile_id
    await run("monitor", device["id"])
    assert all(row["source"] == "snmpv2c" for row in admin_client.get("/api/v1/observations").json()["items"])
    identity = await run("identify", device["id"])
    assert set(identity["result"]["field_sources"].values()) == {"snmpv2c"}
    result = (await run("test_snmpv2c", device["id"]))["result"]
    assert result["success"] and result["protocol"] == "snmpv2c"
    assert "SNMPv2c" in result["message"]
