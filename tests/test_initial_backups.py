import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix import services as svc
from netrix import worker
from netrix.configuration.validation import BackupError
from netrix.discovery import protocols
from netrix.identity.security import encrypt
from netrix.inventory.csv_transfer import render
from netrix.inventory.xlsx_transfer import from_csv
from sqlalchemy import func, select


def payload(client, inventory):
    profile = client.post(
        "/api/v1/credentials",
        json={
            "name": "Initial SSH",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-password"},
        },
    ).json()
    return dict(
        name="Initial switch",
        management_ip="192.0.2.1",
        vrf_id=inventory["vrf"]["id"],
        config_credential_id=profile["id"],
        adapter="aruba_5400",
    )


def test_creation_queues_first_backup_without_schedule_and_deduplicates(admin_client, inventory, env):
    data = payload(admin_client, inventory)
    response = admin_client.post("/api/v1/devices", json=data)
    assert response.status_code == 201
    device = response.json()
    assert device["backup_interval"] == 0
    assert device["backup"]["status"] == "queued"
    manual = admin_client.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]}).json()
    assert manual["id"] == device["backup"]["job_id"]
    # A routine edit must not create another initial backup after completion.
    with env() as db:
        job = db.get(m.Job, manual["id"])
        job.status, job.active_key = "succeeded", None
        db.commit()
    assert (
        admin_client.put("/api/v1/devices/" + device["id"], json={**data, "name": "Renamed"}).status_code
        == 200
    )
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "backup")) == 1


@pytest.mark.parametrize(
    "reason",
    ["outside", "excluded", "disabled", "other_vrf", "planned", "maintenance", "retired", "no_ssh", "rest"],
)
def test_creation_without_authorized_ssh_does_not_queue_backup(admin_client, inventory, env, reason):
    data = payload(admin_client, inventory)
    with env() as db:
        scope = db.get(m.Scope, inventory["scope"]["id"])
        if reason == "excluded":
            scope.exclusions = ["192.0.2.1/32"]
        if reason == "disabled":
            scope.enabled = False
        if reason == "other_vrf":
            vrf = m.VRF(name="Other")
            db.add(vrf)
            db.flush()
            scope.vrf_id = vrf.id
        db.commit()
    if reason == "outside":
        data["management_ip"] = "198.51.100.1"
    if reason in ("planned", "maintenance", "retired"):
        data["lifecycle_status"] = reason
    if reason == "no_ssh":
        data["config_credential_id"] = None
    if reason == "rest":
        profile = admin_client.post(
            "/api/v1/credentials",
            json={
                "name": "API",
                "protocol": "rest",
                "secret": {"token": "fixture"},
            },
        ).json()
        data.update(adapter="rest", config_credential_id=profile["id"])
    response = admin_client.post("/api/v1/devices", json=data)
    if reason in ("outside", "excluded", "disabled", "other_vrf"):
        assert response.status_code == 422
    else:
        assert response.status_code == 201, response.text
        assert response.json()["backup"]["status"] == "skipped"
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "backup")) == 0


def test_initial_backup_is_atomic_with_device_transaction(admin_client, inventory, env):
    data = payload(admin_client, inventory)
    with env() as db:
        user = db.scalar(select(m.User))
        device = svc.save_resource(db, "devices", data, user, commit=False)
        assert device["backup"]["status"] == "queued"
        db.rollback()
    with env() as db:
        assert db.get(m.Device, device["id"]) is None
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_file_import_queues_initial_backup_only_on_apply(
    admin_client, inventory, transfer_profiles, env, format
):
    content = render(
        [
            dict(
                name="Import switch",
                management_ip="192.0.2.1",
                vrf_id="Global",
                snmp_credential_id="SNMP-Profil-01",
                config_credential_id="SSH-Profil-01",
                site_id="Site-01",
                lifecycle_status="active",
                adapter="aruba_5400",
                ssh_trust_host_key=False,
            )
        ]
    )
    if format == "xlsx":
        content = base64.b64encode(from_csv(content)).decode()
    url = f"/api/v1/inventory/devices/{format}/import"
    response = admin_client.post(url, json={"content": content}).json()
    assert response["valid"] == 1 and response["imported"] == 0, response
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
    response = admin_client.post(url, json={"content": content, "apply": True}).json()
    assert response["imported"] == 1, response
    with env() as db:
        device = db.scalar(select(m.Device))
        jobs = db.scalars(select(m.Job).where(m.Job.kind == "backup")).all()
        assert len(jobs) == 1 and jobs[0].target_id == device.id and jobs[0].status == "queued"


async def test_exec_error_with_zero_exit_status_is_not_config(env, monkeypatch):
    @asynccontextmanager
    async def connect(*args, **kwargs):
        async def run(*args, **kwargs):
            return SimpleNamespace(stdout="SSH command execution is not supported.\r\n")

        yield SimpleNamespace(run=run)

    monkeypatch.setattr(protocols.asyncssh, "connect", connect)
    device = SimpleNamespace(adapter="linux", management_ip="192.0.2.1", config_port=22)
    with pytest.raises(BackupError, match="adaptör"):
        await protocols.fetch_config(device, {"username": "fixture", "password": "fixture"})


async def test_worker_rejects_error_and_legacy_content_is_not_presented_as_backup(
    admin_client, inventory, env, monkeypatch
):
    device = admin_client.post("/api/v1/devices", json=payload(admin_client, inventory)).json()
    job = admin_client.post("/api/v1/jobs", json={"kind": "backup", "target_id": device["id"]}).json()

    async def invalid(*args):
        return "SSH command execution is not supported.\r\n"

    monkeypatch.setattr(worker, "fetch_config", invalid)
    await worker.execute(job["id"])
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Snapshot)) == 0
        assert db.get(m.Device, device["id"]).last_backup_at is None
        assert db.get(m.Job, job["id"]).result["error_code"] == "cli_rejected"
        old = m.Snapshot(
            device_id=device["id"],
            job_id=job["id"],
            fingerprint="legacy",
            encrypted_content=encrypt(await invalid()),
            size_bytes=40,
        )
        db.add(old)
        db.commit()
        snapshot_id = old.id
    for suffix in ("content", "diff", "compare-live"):
        call = admin_client.post if suffix == "compare-live" else admin_client.get
        response = call(f"/api/v1/snapshots/{snapshot_id}/{suffix}")
        assert response.status_code == 422, response.text
        assert "yeniden yedek" in response.json()["detail"]
    with env() as db:
        assert db.get(m.Snapshot, snapshot_id) is not None
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "compare")) == 0
