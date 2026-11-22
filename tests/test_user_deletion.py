"""User deletion revokes access and leaves historical references intact."""

from auth_helpers import local_login
from fastapi.testclient import TestClient
from netrix import models as m
from netrix.identity.security import DUMMY_HASH
from netrix.main import app
from sqlalchemy import func, select

USERS = "/api/v1/users"
BULK = USERS + "/bulk-delete"
PASSWORD = "local-fixture-password"


def create(client, name, role="viewer"):
    payload = {
        "email": f"{name}@example.test",
        "display_name": name,
        "role": role,
        "password": PASSWORD,
    }
    response = client.post(USERS, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def sign_in(client, user):
    return local_login(client, json={"email": user["email"], "password": PASSWORD})


def test_single_deletion_revokes_sessions_cleans_private_data_and_preserves_history(admin_client, env):
    user = create(admin_client, "target")
    id = user["id"]
    with TestClient(app, headers={"X-Netrix-Request": "1"}) as other:
        assert sign_in(other, user).status_code == 200
        with env() as db:
            profile = m.UserSSHProfile(owner_id=id, name="Private", encrypted_ssh="fixture")
            db.add(profile)
            db.flush()
            db.add_all(
                [
                    m.AccessGroup(owner_id=id, name="Private group", ssh_profile_id=profile.id),
                    m.UserWorkspace(user_id=id, preferences={}, encrypted_commands="fixture"),
                    m.UserAvatar(user_id=id, preset_id="fixture", version=m.uid()),
                    m.Job(kind="backup", target_id=m.uid(), status="succeeded", requested_by=id),
                ]
            )
            db.commit()
        assert admin_client.delete(f"{USERS}/{id}").status_code == 204
        assert other.get("/api/v1/auth/me").status_code == 401
        assert sign_in(other, user).status_code == 401

    assert admin_client.get(f"{USERS}/{id}").status_code == 404
    assert admin_client.post(f"{USERS}/{id}/toggle").status_code == 404
    assert admin_client.put(f"{USERS}/{id}/roles", json={"role": "admin"}).status_code == 404
    assert admin_client.get(USERS, params={"q": user["email"]}).json()["total"] == 0
    recreated = create(admin_client, "target")
    assert recreated["id"] != id
    with TestClient(app, headers={"X-Netrix-Request": "1"}) as other:
        assert sign_in(other, recreated).json()["id"] == recreated["id"]

    with env() as db:
        deleted = db.get(m.User, id)
        assert deleted.deleted_at and not deleted.is_active and deleted.password_hash == DUMMY_HASH
        assert db.get(m.UserWorkspace, id) is None and db.get(m.UserAvatar, id) is None
        for field in (m.AuthSession.user_id, m.UserSSHProfile.owner_id, m.AccessGroup.owner_id):
            assert db.scalar(select(func.count()).where(field == id)) == 0
        assert db.scalar(select(m.Job.id).where(m.Job.requested_by == id))
        assert db.scalar(select(m.Audit.id).where(m.Audit.actor_id == id, m.Audit.action == "login"))
        removal = db.scalar(select(m.Audit).where(m.Audit.entity_id == id, m.Audit.action == "delete"))
        assert removal and user["email"] in removal.summary


def test_bulk_deletion_is_atomic_and_cannot_delete_self_or_recovery_account(admin_client, env):
    owner = admin_client.get("/api/v1/auth/me").json()
    delegate = create(admin_client, "delegate", "admin")
    first = create(admin_client, "first")
    second = create(admin_client, "second")
    with TestClient(app, headers={"X-Netrix-Request": "1"}) as other:
        assert sign_in(other, delegate).status_code == 200
        assert other.delete(f"{USERS}/{first['id']}").status_code == 403
        assert other.post(BULK, json={"ids": [first["id"]]}).status_code == 403
        assert (
            admin_client.put(f"{USERS}/{delegate['id']}/roles", json={"role": "super_admin"}).status_code
            == 200
        )
        for invalid, status in ((owner["id"], 409), (delegate["id"], 409), (m.uid(), 404)):
            assert other.post(BULK, json={"ids": [first["id"], invalid]}).status_code == status
            assert admin_client.get(f"{USERS}/{first['id']}").status_code == 200
        assert other.post(BULK, json={"ids": []}).status_code == 422
        valid = [first["id"], second["id"], first["id"]]
        assert other.post(BULK, json={"ids": valid}).json() == {"deleted": 2}
    assert admin_client.get(USERS).json()["total"] == 2
    with env() as db:
        assert db.get(m.User, owner["id"]).is_active
        rows = db.scalars(
            select(m.Audit).where(m.Audit.actor_id == delegate["id"], m.Audit.action == "delete")
        )
        assert {row.entity_id for row in rows} == {first["id"], second["id"]}
