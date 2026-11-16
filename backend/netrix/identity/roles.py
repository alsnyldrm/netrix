"""Explicit account role and access changes, with current authority checked under lock."""

from fastapi import HTTPException
from sqlalchemy import delete, select

from .. import models as m
from .permissions import is_admin, is_recovery_owner, is_super_admin
from .security import audit


def locked_accounts(db, actor_id, target_id):
    # The same order is used for grants, revocations and deactivations. Re-read
    # the actor after acquiring the locks so a concurrent demotion cannot leave
    # a request authorized by the earlier session lookup.
    accounts = {
        row.id: row
        for row in db.scalars(
            select(m.User)
            .where(m.User.id.in_({actor_id, target_id}))
            .order_by(m.User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    return accounts.get(actor_id), accounts.get(target_id)


def assign(db, actor_id, target_id, payload):
    actor, target = locked_accounts(db, actor_id, target_id)
    if not is_super_admin(actor) or not actor.is_active:
        raise HTTPException(403, "Bu işlem için süper yönetici yetkisi gerekiyor")
    if not target:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if payload.role == "super_admin" and not target.is_active:
        raise HTTPException(409, "Süper yönetici rolü için önce hesabı etkinleştirin")
    if is_recovery_owner(target) and payload.role != "super_admin":
        raise HTTPException(409, "Yerel kurtarma hesabının süper yönetici rolü kaldırılamaz")
    if target.auth_source == "saml" and target.role != payload.role:
        binding = db.get(m.SamlIdentity, target.id)
        if binding:
            binding.manual_role = True
    target.role, target.ssh_access = payload.role, payload.ssh_access
    audit(
        db, actor, "user_roles_updated", "users", target.id, "Uygulama ve SSH bağlantısı rolleri güncellendi"
    )
    db.commit()
    return target


def toggle(db, actor_id, target_id):
    actor, target = locked_accounts(db, actor_id, target_id)
    if not is_admin(actor) or not actor.is_active:
        raise HTTPException(403, "Bu işlem için yönetici yetkisi gerekiyor")
    if actor_id == target_id:
        raise HTTPException(409, "Kendi hesabınızı devre dışı bırakamazsınız")
    if not target:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if is_super_admin(target) or is_recovery_owner(target):
        raise HTTPException(403, "Süper yönetici hesabı devre dışı bırakılamaz")
    target.is_active = not target.is_active
    db.execute(delete(m.AuthSession).where(m.AuthSession.user_id == target_id))
    audit(db, actor, "toggle_user", "users", target_id, "Hesap erişimi değiştirildi")
    db.commit()
    return target
