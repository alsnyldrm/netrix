import pytest
import test_link_deletions
from netrix import models as m
from sqlalchemy import func, select

link_record = test_link_deletions.link_record
scan = test_link_deletions.scan


def bulk(client, ids, **kwargs):
    return client.post("/api/v1/inventory/links/bulk", json={"ids": ids, "action": "delete", **kwargs})


@pytest.fixture
def more_links(env, link_record):
    with env() as db:
        rows = [
            m.Link(
                device_id=link_record["source"],
                interface_name="A3",
                remote_name="Other",
                remote_port="49",
                source="lldp",
            ),
            m.Link(
                device_id=link_record["new"],
                interface_name="A2",
                remote_name="Old",
                remote_port="NIC",
                source="cdp",
            ),
            m.Link(
                device_id=link_record["source"],
                interface_name="A4",
                remote_name="Keep",
                remote_port="1",
                source="lldp",
            ),
        ]
        db.add_all(rows)
        db.commit()
        return [r.id for r in rows]


def test_bulk_excludes_selected_neighbors_atomically_and_keeps_unselected(
    admin_client, link_record, more_links, env
):
    ids = [link_record["id"], *more_links[:2]]
    response = bulk(admin_client, ids + [ids[0]])
    assert response.status_code == 200 and response.json() == {"updated": 3}
    assert bulk(admin_client, ids).status_code == 200
    with env() as db:
        scan(db, link_record)
        scan(db, link_record, name="Other", port="49", local="A3", chassis="38:21:c7:00:00:03", source="lldp")
        scan(db, {**link_record, "source": link_record["new"]}, source="cdp")
        assert all(db.get(m.Link, id).auto_add_excluded and not db.get(m.Link, id).is_current for id in ids)
        assert db.get(m.Link, more_links[2]).is_current
        assert (
            db.scalar(select(func.count()).select_from(m.Audit).where(m.Audit.action == "delete_link")) == 3
        )
    rows = admin_client.get("/api/v1/inventory/links").json()["items"]
    assert [r["id"] for r in rows] == [more_links[2]]


@pytest.mark.parametrize("invalid", ["missing", "stale", "archived"])
def test_invalid_selection_changes_nothing(admin_client, link_record, more_links, env, invalid):
    invalid_id = more_links[1]
    with env() as db:
        if invalid == "missing":
            invalid_id = "missing"
        elif invalid == "stale":
            db.get(m.Link, invalid_id).is_current = False
        else:
            db.get(m.Device, link_record["new"]).archived = True
        db.commit()
    response = bulk(admin_client, [link_record["id"], more_links[0], invalid_id])
    assert response.status_code == (404 if invalid == "missing" else 409)
    with env() as db:
        for id in (link_record["id"], more_links[0]):
            assert db.get(m.Link, id).is_current and not db.get(m.Link, id).auto_add_excluded
        assert (
            db.scalar(select(func.count()).select_from(m.Audit).where(m.Audit.action == "delete_link")) == 0
        )


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_bulk_delete_requires_admin(admin_client, link_record, env, role):
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    assert bulk(admin_client, [link_record["id"]]).status_code == 403
    assert admin_client.get("/api/v1/inventory/links").json()["total"] == 1


@pytest.mark.parametrize(
    "extra", [{"action": "enable"}, {"action": "update"}, {"changes": {"remote_name": "x"}}]
)
def test_only_deletion_without_changes_is_allowed(admin_client, link_record, extra):
    assert bulk(admin_client, [link_record["id"]], **extra).status_code == 422
    assert admin_client.get("/api/v1/inventory/links").json()["total"] == 1


def test_bulk_selection_bounds(admin_client, link_record):
    assert bulk(admin_client, []).status_code == 422
    assert bulk(admin_client, [link_record["id"]] * 101).status_code == 422
