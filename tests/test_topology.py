import pytest
from netrix import models as m
from netrix.discovery.neighbor_labels import neighbor_label
from netrix.services import serialize
from pysnmp.proto.rfc1902 import OctetString


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (OctetString(bytes.fromhex("187a3b4f1440")), "18:7a:3b:4f:14:40"),
        (bytes.fromhex("ec0273652940").decode("latin1"), "ec:02:73:65:29:40"),
        (OctetString("edge-01"), "edge-01"),
        (OctetString("Kat-İki".encode()), "Kat-İki"),
        ("switch", "switch"),
        ("", ""),
        ("port 1\n", "port 1"),
        (OctetString(b"\xff\x00\x01"), "0xff0001"),
    ],
)
def test_neighbor_labels_preserve_text_and_render_binary(value, expected):
    assert neighbor_label(value) == expected


def test_existing_link_serialization_is_readable_without_mutating_evidence():
    raw = bytes.fromhex("187a3b4f1440").decode("latin1")
    link = m.Link(remote_name=raw, remote_port=raw, interface_name="C3")
    row = serialize(link)
    assert row["remote_name"] == row["remote_port"] == "18:7a:3b:4f:14:40"
    assert link.remote_name == raw


def test_manual_confirmation_is_idempotent_and_keeps_ports_unknown(env):
    from netrix.discovery.manual_links import confirm_link
    from sqlalchemy import func, select

    with env() as db:
        vrf = m.VRF(name="test")
        db.add(vrf)
        db.flush()
        local = m.Device(name="core", management_ip="192.0.2.2", vrf_id=vrf.id)
        remote = m.Device(name="firewall", management_ip="192.0.2.1", vrf_id=vrf.id)
        db.add_all([local, remote])
        db.flush()
        link = confirm_link(db, local.id, remote.id)
        db.commit()
        assert link.source == "manual" and link.confidence == 1
        assert link.interface_name == link.remote_port == ""
        assert confirm_link(db, local.id, remote.id).id == link.id
        assert db.scalar(select(func.count()).select_from(m.Link)) == 1
        assert db.scalar(select(func.count()).select_from(m.Event)) == 1
        with pytest.raises(ValueError):
            confirm_link(db, local.id, local.id)
        remote.archived = True
        with pytest.raises(ValueError):
            confirm_link(db, local.id, remote.id)


def test_collection_reuses_legacy_binary_link(env):
    from netrix.worker import persist_collection
    from sqlalchemy import func, select

    with env() as db:
        vrf = m.VRF(name="test")
        db.add(vrf)
        db.flush()
        device = m.Device(name="core", management_ip="192.0.2.2", vrf_id=vrf.id)
        db.add(device)
        db.flush()
        job = m.Job(kind="identify", target_id=device.id)
        link = m.Link(
            device_id=device.id,
            remote_name=bytes.fromhex("187a3b4f1440").decode("latin1"),
            interface_name="C3",
            remote_port="UPLINK-49",
            source="cdp",
        )
        db.add_all([job, link])
        db.flush()
        old_id = link.id
        persist_collection(
            db,
            device,
            {
                "hostname": "core",
                "interfaces": [],
                "neighbors": [
                    {
                        "interface_name": "C3",
                        "remote_name": "18:7a:3b:4f:14:40",
                        "remote_port": "UPLINK-49",
                        "source": "cdp",
                    }
                ],
            },
            job,
        )
        db.flush()
        assert db.scalar(select(func.count()).select_from(m.Link)) == 1
        assert db.get(m.Link, old_id).remote_name == "18:7a:3b:4f:14:40"
