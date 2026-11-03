"""Release ordering, repository status, immutable selection and downgrade protection."""

from contextlib import asynccontextmanager

import pytest
from netrix import models as m
from netrix.firmware import adapters, runtime
from netrix.firmware.versions import compare
from sqlalchemy import event, select
from test_firmware import fw as firmware_fixture
from test_firmware import make_plan, start

fw = firmware_fixture


@pytest.mark.parametrize(
    "current,target,expected",
    [
        ("PL.10.9.1000", "PL.10.18.1010", -1),
        ("PL.10.18.1010", "PL.10.18.1010", 0),
        ("WC.16.11.26", "WC.16.11.0026", 0),
        ("WC.16.11.1000", "WC.16.11.0026", 1),
        ("K.16.11.0026", "KB.16.11.0026", None),
        ("WB.16.11.0026", "WC.16.11.0026", None),
        ("7.1.070 Release 3507P10", "R3507P9", 1),
        ("7.1.070, Release 3507P10", "R3507P10", 0),
        ("R3507", "R3507P1", -1),
        ("R3507P10", "R5101P10", None),
        ("", "PL.10.18.1010", None),
        ("10.18.1010", "PL.10.18.1010", None),
        ("WC.16.11.0026 beta", "WC.16.11.0026", None),
    ],
)
def test_release_order_never_crosses_software_branches(current, target, expected):
    assert compare(current, target) == expected


def versions(fw, values):
    with fw["sf"]() as db:
        for device, version in zip(fw["devices"], values, strict=True):
            db.get(m.Device, device.id).software_version = version
        db.commit()


def test_repository_status_counts_filters_groups_and_current_or_newer(fw):
    versions(fw, ["WC.16.10.0025", "WC.16.11.0026", "WC.16.12.0001"])
    client = fw["client"]
    rows = client.get("/api/v1/firmware/devices").json()["items"]
    assert [r["update_status"] for r in rows] == ["outdated", "current", "current"]
    assert all(r["latest_version"] == "WC.16.11.0026" for r in rows)
    assert client.get("/api/v1/firmware/overview").json()["devices"] == {
        "current": 2,
        "outdated": 1,
        "unknown": 0,
        "no_image": 0,
    }
    assert client.get("/api/v1/firmware/devices?update_status=current").json()["total"] == 2
    group = client.get("/api/v1/firmware/outdated-groups").json()["items"]
    assert len(group) == 1 and group[0]["id"] == fw["groups"][0]["id"] and group[0]["device_count"] == 1
    assert client.get("/api/v1/firmware/outdated-groups?q=unmatched").json()["total"] == 0


def test_missing_unknown_incompatible_and_uploading_images_never_mark_current(fw):
    versions(fw, ["", "WB.16.10.0025", "WC.16.10.0025"])
    with fw["sf"]() as db:
        db.get(m.Device, fw["devices"][2].id).model = "JL999A"
        source = db.get(m.FirmwareImage, fw["image"]["id"])
        db.add(
            m.FirmwareImage(
                name="Not uploaded",
                family="aos_s",
                version="WC.16.99.9999",
                models=["JL256A"],
                original_name="pending.swi",
                expected_sha256="a" * 64,
                uploaded_by=source.uploaded_by,
            )
        )
        db.commit()
    rows = fw["client"].get("/api/v1/firmware/devices").json()["items"]
    assert [r["update_status"] for r in rows] == ["unknown", "unknown", "no_image"]
    assert not any(r["latest_image_id"] for r in rows)


@pytest.mark.parametrize("mode", ["stage", "upgrade"])
def test_plans_exclude_equal_newer_and_unknown_and_preview_explains_counts(fw, mode):
    versions(fw, ["WC.16.10.0025", "WC.16.11.0026", "WC.16.12.0001"])
    plan = make_plan(fw, mode)
    assert [s["count"] for s in plan["steps"]] == [1, 0]
    assert plan["steps"][0]["excluded"]["current"] == 1
    assert plan["steps"][1]["excluded"]["newer"] == 1
    detail = fw["client"].get("/api/v1/firmware/plans/" + plan["id"]).json()
    assert detail["target_total"] == 1 and detail["targets"][0]["device_id"] == fw["devices"][0].id
    versions(fw, ["WC.16.10.0025", "", "WC.16.12.0001"])
    preview = (
        fw["client"]
        .post(
            "/api/v1/firmware/plans/preview",
            json={
                "name": "Preview",
                "mode": mode,
                "steps": [{"group_id": g["id"], "image_id": fw["image"]["id"]} for g in fw["groups"]],
            },
        )
        .json()
    )
    assert preview["target_total"] == 1 and preview["steps"][0]["excluded"]["unknown"] == 1
    checked = make_plan(fw, "check")
    assert sum(s["count"] for s in checked["steps"]) == 3


def test_fully_current_plan_is_rejected_without_empty_plan_or_targets(fw):
    versions(fw, ["WC.16.11.0026"] * 3)
    response = fw["client"].post(
        "/api/v1/firmware/plans",
        json={
            "name": "Empty",
            "mode": "stage",
            "acknowledge_upgrade_path": True,
            "steps": [{"group_id": fw["groups"][0]["id"], "image_id": fw["image"]["id"]}],
        },
    )
    assert response.status_code == 422 and "Güncellenecek cihaz yok" in response.text
    with fw["sf"]() as db:
        assert not list(db.scalars(select(m.FirmwarePlan)))


def test_selected_devices_and_groups_prepare_frozen_subset_and_reject_foreign_member(fw):
    client = fw["client"]
    steps = client.post("/api/v1/firmware/plans/prepare", json={"device_ids": [fw["devices"][1].id]}).json()[
        "steps"
    ]
    assert steps == [
        {
            "group_id": fw["groups"][0]["id"],
            "image_id": fw["image"]["id"],
            "device_ids": [fw["devices"][1].id],
        }
    ]
    payload = {"name": "Subset", "mode": "stage", "acknowledge_upgrade_path": True, "steps": steps}
    plan = client.post("/api/v1/firmware/plans", json=payload).json()
    assert client.get("/api/v1/firmware/plans/" + plan["id"]).json()["target_total"] == 1
    steps[0]["device_ids"] = [fw["devices"][2].id]
    assert client.post("/api/v1/firmware/plans", json=payload).status_code == 422
    versions(fw, ["WC.16.10.0025", "WC.16.11.0026", "WC.16.10.0025"])
    prepared = client.post(
        "/api/v1/firmware/plans/prepare", json={"group_ids": [fw["groups"][0]["id"]]}
    ).json()
    assert prepared["target_total"] == 1 and prepared["steps"][0]["device_ids"] == [fw["devices"][0].id]
    assert (
        client.post("/api/v1/firmware/plans/prepare", json={"device_ids": [fw["devices"][1].id]}).status_code
        == 409
    )
    assert client.post("/api/v1/firmware/plans/prepare", json={}).status_code == 422


def test_ungrouped_selection_does_not_modify_group_ownership(fw):
    from sqlalchemy import delete

    with fw["sf"]() as db:
        db.execute(delete(m.FirmwareMember).where(m.FirmwareMember.device_id == fw["devices"][2].id))
        db.commit()
    client = fw["client"]
    prepared = client.post("/api/v1/firmware/plans/prepare", json={"include_ungrouped": True}).json()
    assert prepared["steps"][0]["group_id"] is None
    assert prepared["target_total"] == 1
    result = client.post(
        "/api/v1/firmware/plans",
        json={
            "name": "Ungrouped",
            "mode": "stage",
            "steps": prepared["steps"],
            "acknowledge_upgrade_path": True,
        },
    )
    assert result.status_code == 201, result.text
    with fw["sf"]() as db:
        assert (
            db.scalar(select(m.FirmwareMember).where(m.FirmwareMember.device_id == fw["devices"][2].id))
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "live_version,after_backup", [("WC.16.11.0026", False), ("WC.16.12.0001", False), ("WC.16.12.0001", True)]
)
async def test_worker_skips_live_equal_or_newer_without_transfer_or_reboot(
    fw, monkeypatch, live_version, after_backup
):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    target_id = runtime.claim()

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, None

    reads = 0

    async def inspect(*args):
        nonlocal reads
        reads += 1
        return {
            "version": "WC.16.10.0025" if after_backup and reads == 1 else live_version,
            "bank": "primary",
            "banks": "",
        }

    async def probe(*args):
        pass

    async def backup(*args):
        assert after_backup

    async def forbidden(*args):
        raise AssertionError("Current device must not be changed")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "inspect", inspect)
    monkeypatch.setattr(adapters, "probe_sftp", probe)
    monkeypatch.setattr(runtime, "backup", backup)
    monkeypatch.setattr(adapters, "stage", forbidden)
    monkeypatch.setattr(adapters, "activate", forbidden)
    await runtime.execute(target_id)
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, target_id)
        assert target.status == "succeeded" and target.phase == "version_skipped"
        assert target.evidence["skipped_current"] and target.active_device is None
        assert db.get(m.Device, target.device_id).software_version == live_version
        recorded = db.scalars(select(m.FirmwareEvent).where(m.FirmwareEvent.target_id == target_id)).all()
        assert any("güncelleme atlandı" in e.title for e in recorded)


def test_status_queries_are_batched(fw):
    from netrix.firmware import catalog, grouping

    with fw["sf"]() as db:
        statements = []

        def record(*args):
            statements.append(args[2])

        event.listen(db.bind, "before_cursor_execute", record)
        try:
            result = catalog.counts(db, grouping.base_conditions())
        finally:
            event.remove(db.bind, "before_cursor_execute", record)
        assert result["outdated"] == 3 and len(statements) == 2


def test_latest_image_is_numeric_model_compatible_and_not_upload_date(fw):
    with fw["sf"]() as db:
        original = db.get(m.FirmwareImage, fw["image"]["id"])
        for name, version, models in (
            ("Newest compatible", "WC.16.12.0001", ["JL256A"]),
            ("Other model", "WC.16.99.9999", ["JL258A"]),
            ("Old uploaded last", "WC.16.09.9999", ["JL256A"]),
            ("Other branch", "WB.16.99.9999", ["JL256A"]),
        ):
            db.add(
                m.FirmwareImage(
                    name=name,
                    family="aos_s",
                    version=version,
                    models=models,
                    original_name=name.replace(" ", "") + ".swi",
                    expected_sha256="a" * 64,
                    sha256="a" * 64,
                    status="ready",
                    uploaded_by=original.uploaded_by,
                )
            )
        db.commit()
    rows = fw["client"].get("/api/v1/firmware/devices").json()["items"]
    assert all(row["latest_version"] == "WC.16.12.0001" for row in rows)
    assert all(row["update_status"] == "outdated" for row in rows)


def test_empty_and_oversized_explicit_selections_never_expand_to_whole_group(fw):
    client = fw["client"]
    for ids in ([], ["missing"] * 1001):
        payload = {
            "name": "Invalid selection",
            "mode": "stage",
            "acknowledge_upgrade_path": True,
            "steps": [{"group_id": fw["groups"][0]["id"], "image_id": fw["image"]["id"], "device_ids": ids}],
        }
        assert client.post("/api/v1/firmware/plans", json=payload).status_code == 422
    assert (
        client.post("/api/v1/firmware/plans/prepare", json={"device_ids": ["missing"] * 1001}).status_code
        == 422
    )
    with fw["sf"]() as db:
        assert not list(db.scalars(select(m.FirmwareTarget)))


def test_new_planning_endpoints_require_admin_but_status_remains_readable(fw):
    with fw["sf"]() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    client = fw["client"]
    assert client.get("/api/v1/firmware/outdated-groups").status_code == 200
    assert client.get("/api/v1/firmware/plan-images").status_code == 200
    assert (
        client.post("/api/v1/firmware/plans/prepare", json={"device_ids": [fw["devices"][0].id]}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/firmware/plans/preview",
            json={
                "name": "Denied",
                "steps": [{"group_id": fw["groups"][0]["id"], "image_id": fw["image"]["id"]}],
            },
        ).status_code
        == 403
    )


def test_mixed_model_group_preparation_uses_separate_compatible_images(fw):
    with fw["sf"]() as db:
        device = db.get(m.Device, fw["devices"][1].id)
        device.adapter, device.model, device.software_version = "aruba_6100", "JL675A", "PL.10.17.1030"
        original = db.get(m.FirmwareImage, fw["image"]["id"])
        image = m.FirmwareImage(
            name="6100",
            family="cx6100",
            version="PL.10.18.1010",
            models=["JL675A"],
            original_name="6100.swi",
            expected_sha256="c" * 64,
            sha256="c" * 64,
            status="ready",
            uploaded_by=original.uploaded_by,
        )
        db.add(image)
        db.commit()
    result = fw["client"].post("/api/v1/firmware/plans/prepare", json={"group_ids": [fw["groups"][0]["id"]]})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["target_total"] == 2 and len(data["steps"]) == 2
    assert {s["image_id"] for s in data["steps"]} == {image.id, original.id}
    assert all(len(s["device_ids"]) == 1 for s in data["steps"])
    response = fw["client"].post(
        "/api/v1/firmware/plans",
        json={"name": "Mixed", "mode": "stage", "acknowledge_upgrade_path": True, "steps": data["steps"]},
    )
    assert response.status_code == 201, response.text
    assert [s["count"] for s in response.json()["steps"]] == [1, 1]


@pytest.mark.asyncio
async def test_unknown_live_release_stops_without_device_mutation(fw, monkeypatch):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    target_id = runtime.claim()

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, None

    async def inspect(*args):
        return {"version": "WC.16.11.0026 beta", "bank": "primary", "banks": ""}

    async def forbidden(*args):
        raise AssertionError("Unknown live version must not be changed")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "inspect", inspect)
    monkeypatch.setattr(runtime, "backup", forbidden)
    monkeypatch.setattr(adapters, "stage", forbidden)
    monkeypatch.setattr(adapters, "activate", forbidden)
    await runtime.execute(target_id)
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, target_id)
        assert target.status == "failed" and target.error_code == "version"
        assert target.active_device is None and not target.transfer_bytes and not target.snapshot_id


def test_current_device_without_ssh_profile_does_not_block_older_group_members(fw):
    versions(fw, ["WC.16.10.0025", "WC.16.11.0026", "WC.16.12.0001"])
    with fw["sf"]() as db:
        db.get(m.Device, fw["devices"][1].id).config_credential_id = None
        db.commit()
    plan = make_plan(fw, "stage")
    assert sum(s["count"] for s in plan["steps"]) == 1
    assert plan["steps"][0]["excluded"]["current"] == 1
