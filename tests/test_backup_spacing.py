import hashlib

import pytest
from netrix import models as m
from netrix import worker
from netrix.configuration import management
from netrix.configuration.management import snapshot_text
from netrix.discovery.aruba import terminal_text
from netrix.identity.security import decrypt, encrypt
from sqlalchemy import select

HEADER = "; J9851A Configuration Editor; Created on release #KB.16.11\n"
CLEAN = (
    HEADER
    + 'hostname "fixture"\nqos udp-port ipv4 range 50000 50019 dscp ef\nqos tcp-port ipv4 range 50020 50039 dscp af41\n'
)
GAPPED = CLEAN.replace("\nqos tcp", "\n\n\n\nqos tcp")


def test_terminal_cursor_redraw_is_one_boundary_not_blank_lines():
    raw = (
        "qos udp-port ipv4 range 50000 50019 dscp ef\r\n"
        + "\x1b[24;1H\x1b[2K" * 3
        + "qos tcp-port ipv4 range 50020 50039 dscp af41\r\n"
    )
    assert terminal_text(raw) == CLEAN.split('hostname "fixture"\n')[1]
    assert terminal_text("first\x1b[24;1H\x1b[2K\x1b[24;1Hsecond") == "first\nsecond"
    assert terminal_text("banner\r\n\r\nmessage") == "banner\n\nmessage"


def test_existing_snapshot_is_read_without_gaps_but_ciphertext_stays_original(env):
    row = m.Snapshot(encrypted_content=encrypt(GAPPED))
    before = row.encrypted_content
    assert snapshot_text(row) == CLEAN
    assert row.encrypted_content == before and decrypt(before) == GAPPED


@pytest.mark.parametrize(
    "protected",
    [
        'banner motd "first\n\n\nlast"\n',
        'banner motd "first \\"quoted\\"\n\n\nlast"\n',
        "banner motd #\nfirst\n\n\nlast\n#\n",
        "certificate\n-----BEGIN CERTIFICATE-----\nAAA\n\n\nBBB\n-----END CERTIFICATE-----\n",
    ],
)
def test_multiline_value_blank_lines_are_not_removed(env, protected):
    row = m.Snapshot(encrypted_content=encrypt(HEADER + 'hostname "fixture"\n' + protected))
    assert protected in snapshot_text(row)


def test_non_aoss_formats_preserve_blank_lines(env):
    for content in [
        "#config-version=fixture\nconfig system global\n\n\nend\n",
        "!Version AOS-CX\nhostname fixture\n\n\ninterface 1/1/1\n",
    ]:
        assert snapshot_text(m.Snapshot(encrypted_content=encrypt(content))) == content


@pytest.mark.parametrize("changed", [False, True])
async def test_spacing_cleanup_only_reports_real_changes(admin_client, inventory, env, monkeypatch, changed):
    credential = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "Spacing SSH",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-password"},
        },
    ).json()
    device = admin_client.post(
        "/api/v1/devices",
        json={
            "name": "Spacing switch",
            "management_ip": "192.0.2.1",
            "vrf_id": inventory["vrf"]["id"],
            "adapter": "aruba_5400",
            "config_credential_id": credential["id"],
        },
    ).json()
    with env() as db:
        old_job = m.Job(kind="backup", target_id=device["id"], status="succeeded")
        db.add(old_job)
        db.flush()
        old = m.Snapshot(
            device_id=device["id"],
            job_id=old_job.id,
            encrypted_content=encrypt(GAPPED),
            size_bytes=len(GAPPED),
            fingerprint=hashlib.sha256(GAPPED.encode()).hexdigest(),
        )
        db.add(old)
        db.commit()
        old_id = old.id

    async def fetch(*args):
        return CLEAN.replace("dscp af41", "dscp af21") if changed else CLEAN

    monkeypatch.setattr(worker, "fetch_config", fetch)
    await worker.execute(device["backup"]["job_id"])
    with env() as db:
        current = db.scalar(select(m.Snapshot).where(m.Snapshot.job_id == device["backup"]["job_id"]))
        assert current is not None and current.changed is changed
        current_id = current.id
        assert decrypt(db.get(m.Snapshot, old_id).encrypted_content) == GAPPED
    response = admin_client.get(f"/api/v1/snapshots/{current_id}/diff")
    assert response.status_code == 200
    assert bool(response.json()["diff"]) is changed
    assert admin_client.get(f"/api/v1/snapshots/{old_id}/content").json()["content"].count("\n\n\n") == 0

    monkeypatch.setattr(management, "fetch_config", fetch)
    comparison = admin_client.post(f"/api/v1/snapshots/{old_id}/compare-live")
    assert comparison.status_code == 202
    await worker.execute(comparison.json()["id"])
    result = admin_client.get("/api/v1/backup-comparisons/" + comparison.json()["id"]).json()
    assert result["status"] == "succeeded"
    assert result["result"]["changed"] is changed
    assert bool(result["result"]["diff"]) is changed
