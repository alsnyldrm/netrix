"""Persist and preview blacklist drafts without contacting devices."""

from fastapi import APIRouter, Depends

from ..core import db_session
from ..identity.security import admin, current_user, operator
from . import actions, service
from .service import BulkEntryInput, DeviceSync, EntryAction, EntryInput, GroupInput

router = APIRouter(prefix="/api/v1/blacklist", tags=["Kara Liste"])


@router.get("/devices")
def devices(db=Depends(db_session), user=Depends(current_user)):
    return {"families": service.catalog(), "items": service.inventory_choices(db)}


@router.get("/groups")
def groups(db=Depends(db_session), user=Depends(current_user)):
    return {"items": actions.group_list(db)}


@router.post("/groups", status_code=201)
def create_group(payload: GroupInput, db=Depends(db_session), user=Depends(admin)):
    return service.save_group(db, user, payload)


@router.patch("/groups/{group_id}")
def edit_group(group_id: str, payload: GroupInput, db=Depends(db_session), user=Depends(admin)):
    return service.save_group(db, user, payload, group_id)


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, db=Depends(db_session), user=Depends(admin)):
    """Remove the group's ACL content from devices, then delete the group."""
    return actions.delete_group(db, user, group_id)


@router.post("/groups/{group_id}/sync", status_code=202)
def sync_group(group_id: str, db=Depends(db_session), user=Depends(operator)):
    return actions.sync_group(db, user, group_id)


@router.get("/entries")
def entries(db=Depends(db_session), user=Depends(current_user)):
    return {"items": actions.entry_list(db)}


@router.post("/entries", status_code=201)
def create_entry(payload: EntryInput, db=Depends(db_session), user=Depends(operator)):
    return service.save_entry(db, user, payload)


@router.post("/entries/bulk", status_code=201)
def create_entries(payload: BulkEntryInput, db=Depends(db_session), user=Depends(operator)):
    return actions.bulk_create(db, user, payload)


@router.post("/entries/actions", status_code=202)
def entry_actions(payload: EntryAction, db=Depends(db_session), user=Depends(operator)):
    """send: block on devices, remove: unblock and keep the record, delete: unblock then delete."""
    return actions.entry_action(db, user, payload.action, payload.entry_ids)


@router.patch("/entries/{entry_id}")
def edit_entry(entry_id: str, payload: EntryInput, db=Depends(db_session), user=Depends(operator)):
    return service.save_entry(db, user, payload, entry_id)


@router.get("/entries/{entry_id}/preview")
def preview_entry(entry_id: str, db=Depends(db_session), user=Depends(current_user)):
    return service.preview_entry(db, entry_id)


@router.post("/entries/{entry_id}/send", status_code=202)
def send_entry(entry_id: str, db=Depends(db_session), user=Depends(operator)):
    return actions.entry_action(db, user, "send", [entry_id])


@router.delete("/entries/{entry_id}", status_code=202)
def delete_entry(entry_id: str, db=Depends(db_session), user=Depends(operator)):
    return actions.entry_action(db, user, "delete", [entry_id])


@router.get("/device-states")
def device_states(db=Depends(db_session), user=Depends(current_user)):
    return {"items": actions.device_list(db)}


@router.post("/device-states/sync", status_code=202)
def sync_devices(payload: DeviceSync, db=Depends(db_session), user=Depends(operator)):
    return actions.sync_devices(db, user, payload.device_ids)


@router.delete("/device-states/{device_id}")
def forget_device(device_id: str, db=Depends(db_session), user=Depends(admin)):
    """Forget a recorded device state without contacting the device."""
    return actions.forget_device(db, user, device_id)
