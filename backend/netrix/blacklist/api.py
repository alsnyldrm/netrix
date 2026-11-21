"""Persist and preview blacklist drafts without contacting devices."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from .. import models as m
from ..core import db_session
from ..identity.security import admin, current_user, operator
from . import service
from .service import EntryInput, GroupInput

router = APIRouter(prefix="/api/v1/blacklist", tags=["Kara Liste"])


@router.get("/devices")
def devices(db=Depends(db_session), user=Depends(current_user)):
    return {"families": service.catalog(), "items": service.inventory_choices(db)}


@router.get("/groups")
def groups(db=Depends(db_session), user=Depends(current_user)):
    members = {}
    for group_id, device_id in db.execute(select(m.ACLGroupDevice.group_id, m.ACLGroupDevice.device_id)):
        members.setdefault(group_id, []).append(device_id)
    return {
        "items": [
            service.group_view(row, members.get(row.id, []))
            for row in db.scalars(select(m.ACLGroup).order_by(m.ACLGroup.name, m.ACLGroup.id))
        ]
    }


@router.post("/groups", status_code=201)
def create_group(payload: GroupInput, db=Depends(db_session), user=Depends(admin)):
    return service.save_group(db, user, payload)


@router.patch("/groups/{group_id}")
def edit_group(group_id: str, payload: GroupInput, db=Depends(db_session), user=Depends(admin)):
    return service.save_group(db, user, payload, group_id)


@router.get("/entries")
def entries(db=Depends(db_session), user=Depends(current_user)):
    memberships = {}
    for entry_id, group_id in db.execute(
        select(m.BlacklistEntryGroup.entry_id, m.BlacklistEntryGroup.group_id)
    ):
        memberships.setdefault(entry_id, []).append(group_id)
    return {
        "items": [
            service.entry_view(row, memberships.get(row.id, []))
            for row in db.scalars(
                select(m.BlacklistEntry).order_by(m.BlacklistEntry.updated_at.desc(), m.BlacklistEntry.id)
            )
        ]
    }


@router.post("/entries", status_code=201)
def create_entry(payload: EntryInput, db=Depends(db_session), user=Depends(operator)):
    return service.save_entry(db, user, payload)


@router.patch("/entries/{entry_id}")
def edit_entry(entry_id: str, payload: EntryInput, db=Depends(db_session), user=Depends(operator)):
    return service.save_entry(db, user, payload, entry_id)


@router.get("/entries/{entry_id}/preview")
def preview_entry(entry_id: str, db=Depends(db_session), user=Depends(current_user)):
    return service.preview_entry(db, entry_id)
