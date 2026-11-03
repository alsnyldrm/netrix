import asyncio
import json
import secrets
import time

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy import delete, select

from .. import models as m
from ..core import db_session, session_factory, settings
from ..identity.security import audit, current_user, session_user, token_hash
from . import ephemeral as e
from . import schemas as s
from . import service as svc

router = APIRouter(prefix="/api/v1/access", tags=["User workspace & SSH"])


@router.get("/preferences")
def preferences(user=Depends(current_user), db=Depends(db_session)):
    return svc.preferences(db, user)


@router.put("/preferences")
def save_preferences(payload: s.Preferences, user=Depends(current_user), db=Depends(db_session)):
    svc.workspace(db, user).preferences = payload.model_dump()
    db.commit()
    return payload


@router.put("/preferences/terminal")
def save_terminal_preferences(
    payload: s.TerminalAppearance, user=Depends(current_user), db=Depends(db_session)
):
    svc.lock_owner(db, user)
    preferences = svc.preferences(db, user)
    preferences["terminal"] = payload.model_dump()
    svc.workspace(db, user).preferences = preferences
    db.commit()
    return preferences


@router.get("/ssh-profiles")
def ssh_profiles(user=Depends(current_user), db=Depends(db_session)):
    return {"items": svc.list_profiles(db, user)}


@router.post("/ssh-profiles", status_code=201)
def add_ssh(payload: s.SSHProfile, user=Depends(current_user), db=Depends(db_session)):
    return svc.save_ssh(db, user, payload)


@router.put("/ssh-profiles/{id}")
def save_ssh(id: str, payload: s.SSHProfile, user=Depends(current_user), db=Depends(db_session)):
    return svc.save_ssh(db, user, payload, id)


@router.delete("/ssh-profiles/{id}", status_code=204)
def delete_ssh(id: str, user=Depends(current_user), db=Depends(db_session)):
    svc.delete_profile(db, user, id)


@router.get("/commands")
def commands(user=Depends(current_user), db=Depends(db_session)):
    return {"items": svc.commands(db, user)}


@router.put("/commands")
def save_commands(payload: s.Commands, user=Depends(current_user), db=Depends(db_session)):
    svc.workspace(db, user).encrypted_commands = e.pack([c.model_dump() for c in payload.items])
    db.commit()
    return payload


@router.get("/devices")
def devices(
    q: str = Query(default="", max_length=120),
    filters: str = Query(default="[]", max_length=20000),
    offset: int = Query(default=0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    from ..inventory.management import query

    result = query(db, "devices", limit=100, offset=offset, q=q, filters=filters)
    assignments = dict(
        db.execute(
            select(m.AccessGroupDevice.device_id, m.AccessGroupDevice.group_id).where(
                m.AccessGroupDevice.owner_id == user.id,
                m.AccessGroupDevice.device_id.in_([d["id"] for d in result["items"]]),
            )
        ).all()
    )
    names = dict(
        db.execute(
            select(m.AccessGroup.id, m.AccessGroup.name).where(m.AccessGroup.owner_id == user.id)
        ).all()
    )
    for device in result["items"]:
        group_id = assignments.get(device["id"])
        device.update(access_group_id=group_id, access_group_name=names.get(group_id))
    return {**result, "has_more": offset + len(result["items"]) < result["total"]}


@router.get("/device-selection")
def device_selection(
    q: str = Query(default="", max_length=120),
    filters: str = Query(default="[]", max_length=20000),
    group_id: str = "",
    user=Depends(current_user),
    db=Depends(db_session),
):
    from ..inventory.management import query

    if group_id:
        svc.owned_group(db, user, group_id)
    result = query(db, "devices", q=q, filters=filters, ids_only=True)
    occupied = set(
        db.scalars(
            select(m.AccessGroupDevice.device_id).where(
                m.AccessGroupDevice.owner_id == user.id,
                m.AccessGroupDevice.group_id != group_id,
                m.AccessGroupDevice.device_id.in_(result["ids"]),
            )
        )
    )
    return {
        "ids": [id for id in result["ids"] if id not in occupied],
        "skipped": len(occupied),
        "total": result["total"],
    }


@router.get("/device-filter-values")
def device_filter_values(
    field: str,
    q: str = Query(default="", max_length=120),
    user=Depends(current_user),
    db=Depends(db_session),
):
    from ..inventory.management import query

    return query(db, "devices", q=q, value_field=field)


@router.get("/groups")
def groups(user=Depends(current_user), db=Depends(db_session)):
    return {"items": svc.list_groups(db, user)}


@router.post("/groups", status_code=201)
def add_group(payload: s.GroupInput, user=Depends(current_user), db=Depends(db_session)):
    return svc.save_group(db, user, payload)


@router.put("/groups/{id}")
def save_group(id: str, payload: s.GroupInput, user=Depends(current_user), db=Depends(db_session)):
    return svc.save_group(db, user, payload, id)


@router.delete("/groups/{id}", status_code=204)
def delete_group(id: str, user=Depends(current_user), db=Depends(db_session)):
    svc.lock_owner(db, user)
    group = svc.owned_group(db, user, id)
    db.execute(delete(m.AccessGroup).where(m.AccessGroup.id == group.id))
    audit(db, user, "access_group_deleted", "access_group", id, "Cihaz grubu silindi")
    db.commit()


@router.post("/sessions", status_code=201)
def open_session(
    payload: s.SessionInput, request: Request, user=Depends(current_user), db=Depends(db_session)
):
    device = svc.authorize_device(db, user, payload.device_id)
    profile_id, _ = svc.resolve_profile(db, user, device.id)
    value = {
        "ssh_profile_id": profile_id,
        **payload.model_dump(),
        "user_id": user.id,
        "auth_hash": token_hash(request.cookies.get("netrix_session", "")),
        "device_name": device.name,
        "management_ip": device.management_ip,
    }
    result = e.admit("session", value)
    audit(db, user, "ssh_session_opened", "device", device.id, "Etkileşimli SSH oturumu istendi")
    db.commit()
    return {**result, "device_name": device.name, "management_ip": device.management_ip}


@router.get("/sessions/{id}")
def session_info(id: str, user=Depends(current_user)):
    value = e.read(e.redis_client(), "session", id, user)
    return {k: value.get(k) for k in ("id", "status", "device_id", "device_name", "management_ip", "error")}


@router.delete("/sessions/{id}", status_code=204)
def close_session(id: str, user=Depends(current_user)):
    client = e.redis_client()
    e.read(client, "session", id, user)
    client.set(e.key("cancel", id), "1", ex=e.TTL)


@router.post("/batches", status_code=202)
def batch(payload: s.BatchInput, request: Request, user=Depends(current_user), db=Depends(db_session)):
    targets = svc.batch_targets(db, user, payload.device_ids)
    result = e.admit(
        "batch",
        {
            "user_id": user.id,
            "auth_hash": token_hash(request.cookies.get("netrix_session", "")),
            "command": payload.command.get_secret_value(),
            "timeout": payload.timeout,
            "targets": targets,
        },
    )
    audit(db, user, "ssh_batch_requested", "user", user.id, f"{len(targets)} cihaz için toplu komut istendi")
    db.commit()
    return result


@router.post("/batch-drafts", status_code=201)
def batch_draft(payload: s.BatchDraftInput, user=Depends(current_user), db=Depends(db_session)):
    targets = svc.batch_targets(db, user, payload.device_ids)
    return e.draft(
        {
            "user_id": user.id,
            "targets": targets,
            "command": payload.command.get_secret_value(),
            "timeout": payload.timeout,
        }
    )


@router.get("/batch-drafts/{id}")
def read_batch_draft(id: str, user=Depends(current_user)):
    value = e.read(e.redis_client(), "draft", id, user)
    return {k: value[k] for k in ("id", "targets", "command", "timeout")}


@router.delete("/batch-drafts/{id}", status_code=204)
def delete_batch_draft(id: str, user=Depends(current_user)):
    client = e.redis_client()
    value = e.read(client, "draft", id, user)
    client.delete(e.key("draft", id))
    client.zrem(e.key("drafts", value["user_id"]), id)


@router.get("/batches/{id}")
def batch_result(id: str, user=Depends(current_user)):
    client = e.redis_client()
    value = e.read(client, "batch", id, user)
    targets = value.get("targets", [])
    if targets:
        updates = client.hmget(e.key("batch-targets", id), [target["device_id"] for target in targets])
        value["targets"] = [
            e.unpack(update) if update else target for target, update in zip(targets, updates)
        ]
    return {k: value.get(k) for k in ("id", "status", "targets", "error", "timeout")}


@router.delete("/batches/{id}", status_code=204)
def cancel_batch(id: str, user=Depends(current_user)):
    client = e.redis_client()
    e.read(client, "batch", id, user)
    client.set(e.key("cancel", id), "1", ex=e.TTL)


def ws_identity(token, device_id=None):
    with session_factory()() as db:
        user = session_user(db, token)
        if user and device_id:
            svc.authorize_device(db, user, device_id)
        return user


@router.websocket("/sessions/{id}/ws")
async def terminal(ws: WebSocket, id: str):
    if ws.headers.get("origin") != settings().public_url:
        await ws.close(code=1008)
        return
    client = Redis.from_url(settings().redis_url, decode_responses=True, socket_connect_timeout=2)
    token = ws.cookies.get("netrix_session", "")
    attachment = secrets.token_hex(16)
    try:
        value = e.unpack(await client.get(e.key("session", id)))
        user = await asyncio.to_thread(ws_identity, token, value["device_id"] if value else None)
        if not value or not user or user.id != value["user_id"] or token_hash(token) != value["auth_hash"]:
            await ws.close(code=1008)
            return
        await ws.accept()
        await client.set(e.key("attachment", id), attachment, ex=e.TTL)
        await client.set(e.key("viewer", id), "1", ex=40)

        async def output():
            cursor = "0-0"
            checked = 0
            while True:
                if time.monotonic() - checked >= 10:
                    if await client.get(e.key("attachment", id)) != attachment:
                        await ws.close(code=4001)
                        return
                    if not await asyncio.to_thread(ws_identity, token, value["device_id"]):
                        await ws.close(code=1008)
                        return
                    await client.set(e.key("viewer", id), "1", ex=40)
                    state = e.unpack(await client.get(e.key("session", id)))
                    await ws.send_json(
                        {
                            "type": "status",
                            "status": state.get("status", "closed") if state else "closed",
                            "error": state.get("error", "") if state else "Oturumun süresi doldu",
                        }
                    )
                    checked = time.monotonic()
                events = await client.xread({e.key("out", id): cursor}, count=64, block=500)
                for _, messages in events:
                    for cursor, fields in messages:
                        await ws.send_json(e.unpack(fields["data"]))

        async def incoming():
            window, size = time.monotonic(), 0
            while True:
                raw = await ws.receive_text()
                if len(raw) > 20000:
                    await ws.close(code=1009)
                    return
                if time.monotonic() - window > 1:
                    window, size = time.monotonic(), 0
                size += len(raw)
                if size > 65536:
                    await ws.close(code=1008)
                    return
                if await client.get(e.key("attachment", id)) != attachment:
                    await ws.close(code=4001)
                    return
                data = json.loads(raw)
                if (
                    data.get("type") == "input"
                    and isinstance(data.get("data"), str)
                    and len(data["data"]) <= 8192
                ):
                    message = {"type": "input", "data": data["data"]}
                elif (
                    data.get("type") == "resize"
                    and type(data.get("cols")) is int
                    and type(data.get("rows")) is int
                ):
                    message = {
                        "type": "resize",
                        "cols": max(20, min(300, data["cols"])),
                        "rows": max(5, min(100, data["rows"])),
                    }
                else:
                    continue
                await client.xadd(e.key("in", id), {"data": e.pack(message)}, maxlen=128)
                await client.expire(e.key("in", id), e.TTL)

        tasks = [asyncio.create_task(output()), asyncio.create_task(incoming())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        try:
            await ws.close(code=1008)
        except RuntimeError:
            pass
    finally:
        await client.aclose()
