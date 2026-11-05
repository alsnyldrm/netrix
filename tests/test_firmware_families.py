"""Hardware family selection uses model evidence and never merges software branches."""

from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.firmware import runtime
from netrix.firmware.service import compatible, transfer_protocol
from test_firmware import DIGEST
from test_firmware import fw as firmware_fixture

fw = firmware_fixture
IMAGES = [
    ("aos_s_54xx", "K.16.02.0036"),
    ("aos_s_54xx", "KB.16.11.0032"),
    ("aos_s_29xx", "WB.16.11.0001"),
    ("aos_s_29xx", "WC.16.11.0032"),
    ("cx6100", "PL.10.18.1010"),
    ("hp1950", "R3507P10"),
    ("hp1950", "R5106P06"),
]


@pytest.mark.parametrize(
    "adapter,model,index",
    [
        ("aruba_5400", "J8697A", 0),
        ("aruba_5400", "5406-J9850A", 1),
        ("aruba_5400", "5412-J9851A", 1),
        ("aruba_2900", "2920-J9726A", 2),
        ("aruba_2900", "2930F-JL256A", 3),
        ("aruba_2900", "JL261A", 3),
        ("aruba_2900", "JL558A", 3),
        ("aruba_6100", "6100-JL675A", 4),
        ("aruba_6100", "R9Y04A", 4),
        ("hp_1950", "1950-JG962A", 5),
        ("hp_1950", "1950-JH295A", 6),
        ("aruba_2900", "Aruba 2920", 2),
        ("aruba_2900", "Aruba 2930F", 3),
    ],
)
def test_automatic_compatibility_identifies_model_and_exact_branch(adapter, model, index):
    device = SimpleNamespace(adapter=adapter, model=model, software_version=IMAGES[index][1])
    for n, (family, version) in enumerate(IMAGES):
        assert compatible(SimpleNamespace(family=family, version=version, models=[]), device) == (n == index)


@pytest.mark.parametrize(
    "model", ["", "unknown", "JL999A", "2920-JL256A", "2930F J9726A", "JL256A J9850A", "6000-JL256A"]
)
def test_uncertain_or_conflicting_model_cannot_become_automatically_compatible(model):
    device = SimpleNamespace(adapter="aruba_2900", model=model, software_version="WC.16.10.0025")
    assert not compatible(SimpleNamespace(family="aos_s_29xx", version="WC.16.11.0032", models=[]), device)


@pytest.mark.parametrize("family,version", IMAGES)
def test_image_upload_does_not_require_manual_model_codes(fw, family, version):
    response = fw["client"].post(
        "/api/v1/firmware/images",
        json={
            "name": "Automatic model compatibility",
            "family": family,
            "version": version,
            "original_name": "automatic.ipe" if family == "hp1950" else "automatic.swi",
            "expected_sha256": DIGEST,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["models"] == []
    assert transfer_protocol(family) == (
        "tftp" if family == "hp1950" else "scp" if family == "cx6100" else "sftp"
    )


@pytest.mark.parametrize(
    "family,version",
    [
        ("aos_s_54xx", "WC.16.11.0032"),
        ("aos_s_54xx", "WB.16.11.0001"),
        ("aos_s_29xx", "KB.16.11.0032"),
        ("aos_s_29xx", "K.16.02.0036"),
        ("cx6100", "WC.16.11.0032"),
        ("hp1950", "R9900P01"),
        ("aos_s", "WC.16.11.0032"),
    ],
)
def test_api_rejects_wrong_branch_and_removed_combined_family(fw, family, version):
    response = fw["client"].post(
        "/api/v1/firmware/images",
        json={
            "name": "Wrong family",
            "family": family,
            "version": version,
            "original_name": "bad.ipe" if family == "hp1950" else "bad.swi",
            "expected_sha256": DIGEST,
        },
    )
    assert response.status_code == 422


def test_family_filters_split_54xx_from_29xx_and_old_model_notes_do_not_limit_family(fw):
    with fw["sf"]() as db:
        device = db.get(m.Device, fw["devices"][0].id)
        device.adapter, device.model, device.software_version = "aruba_5400", "J9850A", "KB.16.10.0025"
        image = db.get(m.FirmwareImage, fw["image"]["id"])
        other = db.get(m.Device, fw["devices"][1].id)
        image.models = ["JL558A"]
        assert compatible(image, other)
        db.commit()
    c = fw["client"]
    assert c.get("/api/v1/firmware/devices", params={"family": "aos_s_54xx"}).json()["total"] == 1
    assert c.get("/api/v1/firmware/devices", params={"family": "aos_s_29xx"}).json()["total"] == 2
    assert c.get("/api/v1/firmware/devices", params={"family": "aos_s"}).status_code == 422
    assert runtime.AOS_S_FAMILIES == ("aos_s_54xx", "aos_s_29xx")


@pytest.mark.parametrize(
    "adapter,model,current,family,target,old_models",
    [
        ("aruba_6100", "6100", "PL.10.17.1030", "cx6100", "PL.10.18.1010", ["JL675A"]),
        ("aruba_6100", "6100", "PL.10.18.1010", "cx6100", "PL.10.18.1010", ["JL675A"]),
        ("aruba_6100", "6100", "", "cx6100", "PL.10.18.1010", ["JL675A"]),
        ("aruba_6100", "JL677A", "PL.10.17.1030", "cx6100", "PL.10.18.1010", ["JL675A"]),
        ("aruba_2900", "2930F", "WC.16.10.0025", "aos_s_29xx", "WC.16.11.0032", ["JL256A"]),
        ("aruba_2900", "JL558A", "WC.16.10.0025", "aos_s_29xx", "WC.16.11.0032", ["JL256A"]),
        ("aruba_5400", "5400R", "KB.16.10.0025", "aos_s_54xx", "KB.16.11.0032", ["J9850A"]),
    ],
)
def test_old_upload_model_notes_accept_confirmed_hardware_family(
    adapter, model, current, family, target, old_models
):
    device = SimpleNamespace(adapter=adapter, model=model, software_version=current)
    image = SimpleNamespace(family=family, version=target, models=old_models)
    assert compatible(image, device)
    assert image.models == old_models  # Retain history; do not rewrite upload metadata.


@pytest.mark.parametrize("family", ["cx6100", "aos_s_29xx"])
def test_generic_series_with_legacy_upload_has_current_outdated_and_unknown_states_without_groups(fw, family):
    from sqlalchemy import func, select

    cx = family == "cx6100"
    older, target = ("PL.10.17.1030", "PL.10.18.1010") if cx else ("WC.16.10.0025", "WC.16.11.0026")
    with fw["sf"]() as db:
        image = db.get(m.FirmwareImage, fw["image"]["id"])
        image.family, image.version, image.models = family, target, ["JL675A"] if cx else ["JL256A"]
        for device, version in zip(fw["devices"], (older, target, ""), strict=True):
            row = db.get(m.Device, device.id)
            row.adapter, row.model, row.software_version = (
                ("aruba_6100", "6100", version) if cx else ("aruba_2900", "2930F", version)
            )
        db.commit()
    client = fw["client"]
    for group in fw["groups"]:
        assert client.delete("/api/v1/firmware/groups/" + group["id"]).status_code == 204
    rows = client.get("/api/v1/firmware/devices", params={"image_id": image.id}).json()["items"]
    assert [r["update_status"] for r in rows] == ["outdated", "current", "unknown"]
    assert all(r["compatible"] for r in rows)
    assert client.get("/api/v1/firmware/overview").json()["devices"] == {
        "outdated": 1,
        "current": 1,
        "unknown": 1,
        "no_image": 0,
    }
    selection = client.post(
        "/api/v1/firmware/plans/prepare", json={"device_ids": [fw["devices"][0].id]}
    ).json()
    assert selection["target_total"] == 1
    response = client.post(
        "/api/v1/firmware/plans",
        json={
            "name": "Legacy family selection",
            "mode": "stage",
            "steps": [{"image_id": image.id, "device_ids": [d.id for d in fw["devices"]]}],
            "acknowledge_upgrade_path": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["steps"][0]["excluded"] == {"current": 1, "newer": 0, "unknown": 1}
    with fw["sf"]() as db:
        assert db.scalar(select(func.count()).select_from(m.FirmwareGroup)) == 0
        assert db.scalar(select(func.count()).select_from(m.FirmwareTarget)) == 1
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
