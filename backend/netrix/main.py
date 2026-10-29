import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from . import models as m
from . import schemas as s
from . import services as svc
from .configuration.diff import config_diff, redact_config
from .core import db_session, engine, now, redis_client, session_factory, settings
from .identity.security import (
    DUMMY_HASH,
    admin,
    audit,
    current_user,
    decrypt,
    hasher,
    issue_session,
    operator,
    session_user,
    token_hash,
    verify,
)


@asynccontextmanager
async def lifespan(app):
    if not settings().encryption_key or not settings().setup_token:
        raise RuntimeError("NETRIX_ENCRYPTION_KEY and NETRIX_SETUP_TOKEN are required")
    yield


app = FastAPI(
    title="NETRIX API",
    version="1.0.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)
P = "/api/v1"


@app.middleware("http")
async def security_headers(request, call_next):
    request_id = secrets.token_hex(12)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if request.headers.get("x-netrix-request") != "1" or (origin and origin != settings().public_url):
            return JSONResponse({"detail": "İstek doğrulanamadı", "request_id": request_id}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse(
        {"detail": "Bu kayıt zaten var veya başka kayıtlar tarafından kullanılıyor"}, status_code=409
    )


@app.exception_handler(OperationalError)
async def database_error(request, exc):
    code = exc.orig.args[0] if getattr(exc, "orig", None) and exc.orig.args else None
    if code in (4025, 3819):
        return JSONResponse({"detail": "Veritabanı kısıtı bu kaydı reddetti"}, status_code=409)
    return JSONResponse({"detail": "Veri hizmeti geçici olarak kullanılamıyor"}, status_code=503)


def validation_response(exc):
    return JSONResponse(
        {"detail": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
        status_code=422,
    )


@app.exception_handler(RequestValidationError)
async def request_validation(request, exc):
    return validation_response(exc)


@app.exception_handler(ValidationError)
async def value_validation(request, exc):
    return validation_response(exc)


@app.get(P + "/health/live")
def live():
    return {"status": "ok", "application": "netrix"}


@app.get(P + "/health/ready")
def ready(response: Response):
    components = {}
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "unavailable"
    try:
        components["redis"] = "ok" if redis_client().ping() else "unavailable"
    except Exception:
        components["redis"] = "unavailable"
    response.status_code = 503 if "unavailable" in components.values() else 200
    return {"status": "ok" if response.status_code == 200 else "degraded", "components": components}


@app.get(P + "/auth/status")
def auth_status(db=Depends(db_session)):
    return {"setup_required": db.scalar(select(func.count()).select_from(m.User)) == 0}


@app.post(P + "/auth/setup", status_code=201)
def setup(payload: s.SetupInput, request: Request, db=Depends(db_session)):
    rate_limit("setup:" + request.client.host)
    state = db.scalar(select(m.SystemState).where(m.SystemState.key == "setup").with_for_update())
    if not state or state.value == "complete" or db.scalar(select(func.count()).select_from(m.User)):
        raise HTTPException(409, "İlk kurulum tamamlanmış")
    if not secrets.compare_digest(payload.setup_token, settings().setup_token):
        raise HTTPException(403, "Kurulum anahtarı geçersiz")
    user = m.User(
        email=payload.email,
        display_name=payload.display_name,
        role="admin",
        password_hash=hasher.hash(payload.password),
    )
    db.add(user)
    db.flush()
    state.value = "complete"
    db.add(m.VRF(name="Global", description="Varsayılan yönlendirme alanı"))
    audit(db, user, "setup", "users", user.id, "NETRIX ilk yönetici kurulumu tamamlandı")
    db.commit()
    return svc.serialize(user)


def rate_limit(key):
    try:
        client = redis_client()
        key = "netrix:auth:" + token_hash(key)
        count = client.incr(key)
        if count == 1:
            client.expire(key, 300)
        if count > 15:
            raise HTTPException(429, "Çok fazla deneme. Beş dakika sonra tekrar deneyin")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Kimlik servisi geçici olarak kullanılamıyor") from exc


@app.post(P + "/auth/login")
def login(payload: s.LoginInput, request: Request, response: Response, db=Depends(db_session)):
    rate_limit(request.client.host)
    user = db.scalar(select(m.User).where(m.User.email == payload.email.casefold()))
    valid = verify(payload.password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or not user.is_active:
        raise HTTPException(401, "E-posta veya parola hatalı")
    token = issue_session(db, user)
    audit(db, user, "login", "users", user.id, "Oturum açıldı")
    db.commit()
    response.set_cookie(
        "netrix_session",
        token,
        httponly=True,
        secure=settings().secure_cookies,
        samesite="strict",
        max_age=43200,
        path="/",
    )
    return svc.serialize(user)


@app.get(P + "/auth/me")
def me(user=Depends(current_user)):
    return svc.serialize(user)


@app.post(P + "/auth/logout", status_code=204)
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(db_session)):
    db.execute(
        delete(m.AuthSession).where(
            m.AuthSession.token_hash == token_hash(request.cookies.get("netrix_session", ""))
        )
    )
    db.commit()
    response.delete_cookie("netrix_session", path="/")


@app.post(P + "/auth/password", status_code=204)
def password(
    payload: s.PasswordInput,
    request: Request,
    response: Response,
    user=Depends(current_user),
    db=Depends(db_session),
):
    if not verify(payload.current_password, user.password_hash):
        raise HTTPException(403, "Mevcut parola hatalı")
    user.password_hash = hasher.hash(payload.new_password)
    db.execute(delete(m.AuthSession).where(m.AuthSession.user_id == user.id))
    audit(db, user, "password_change", "users", user.id, "Parola değiştirildi; oturumlar kapatıldı")
    db.commit()
    response.delete_cookie("netrix_session", path="/")


@app.get(P + "/dashboard")
def dashboard(user=Depends(current_user), db=Depends(db_session)):
    counts = {
        name: db.scalar(select(func.count()).select_from(model))
        for name, model in [
            ("devices", m.Device),
            ("prefixes", m.Prefix),
            ("addresses", m.IPAddress),
            ("snapshots", m.Snapshot),
            ("sites", m.Site),
        ]
    }
    counts["reachable"] = db.scalar(
        select(func.count())
        .select_from(m.Device)
        .where(m.Device.reachability == "reachable", m.Device.lifecycle_status == "active")
    )
    counts["active_devices"] = db.scalar(
        select(func.count()).select_from(m.Device).where(m.Device.lifecycle_status == "active")
    )
    counts["firing_alerts"] = db.scalar(
        select(func.count()).select_from(m.Alert).where(m.Alert.state == "firing")
    )
    counts["running_jobs"] = db.scalar(
        select(func.count()).select_from(m.Job).where(m.Job.status.in_(["queued", "running"]))
    )
    counts["successful_discoveries"] = db.scalar(
        select(func.count())
        .select_from(m.Job)
        .where(m.Job.kind == "discovery", m.Job.status.in_(["succeeded", "partial"]))
    )
    counts["monitored"] = db.scalar(
        select(func.count()).select_from(m.Device).where(m.Device.monitoring_enabled.is_(True))
    )
    groups = db.execute(select(m.Device.kind, func.count()).group_by(m.Device.kind)).all()
    last = db.scalar(select(func.max(m.Sample.created_at)))
    return {
        "counts": counts,
        "device_kinds": [{"kind": kind, "count": count} for kind, count in groups],
        "last_sample_at": last.isoformat() if last else None,
        "server_time": now().isoformat(),
    }


@app.get(P + "/system")
def system(user=Depends(current_user), db=Depends(db_session)):
    data = {
        "application": "netrix",
        "version": "1.0.0",
        "database": engine().dialect.name,
        "public_url": settings().public_url,
        "retention_days": settings().sample_retention_days,
        "time": now().isoformat(),
    }
    try:
        client = redis_client()
        data["redis"] = "ok" if client.ping() else "unavailable"
        data["worker"] = client.get("netrix:worker:heartbeat")
        data["scheduler"] = client.get("netrix:scheduler:heartbeat")
    except Exception:
        data.update(redis="unavailable", worker=None, scheduler=None)
    return data


@app.get(P + "/traffic")
def traffic(
    interface_id: str | None = None,
    device_id: str | None = None,
    hours: int = Query(24, ge=1, le=168),
    user=Depends(current_user),
    db=Depends(db_session),
):
    stmt = (
        select(m.Sample)
        .join(m.Interface, m.Sample.interface_id == m.Interface.id)
        .where(m.Sample.created_at >= now() - timedelta(hours=hours))
    )
    if interface_id:
        stmt = stmt.where(m.Sample.interface_id == interface_id)
    if device_id:
        stmt = stmt.where(m.Interface.device_id == device_id)
    rows = list(db.scalars(stmt.order_by(m.Sample.created_at.desc()).limit(2000)))
    return {"items": [svc.serialize(row) for row in reversed(rows)], "limited": len(rows) == 2000}


@app.get(P + "/snapshots/{id}/content")
def snapshot_content(id: str, user=Depends(operator), db=Depends(db_session)):
    row = svc.get(db, m.Snapshot, id)
    audit(db, user, "read_config", "snapshots", id, "Maskelenmiş konfigürasyon görüntülendi")
    db.commit()
    return {"content": redact_config(decrypt(row.encrypted_content)), "redacted": True}


@app.get(P + "/snapshots/{id}/diff")
def snapshot_diff(id: str, previous_id: str | None = None, user=Depends(operator), db=Depends(db_session)):
    row = svc.get(db, m.Snapshot, id)
    previous = (
        svc.get(db, m.Snapshot, previous_id)
        if previous_id
        else db.scalar(
            select(m.Snapshot)
            .where(m.Snapshot.device_id == row.device_id, m.Snapshot.created_at < row.created_at)
            .order_by(m.Snapshot.created_at.desc())
            .limit(1)
        )
    )
    if previous and previous.device_id != row.device_id:
        raise HTTPException(422, "Sürümler aynı cihaza ait olmalı")
    return {
        "diff": config_diff(
            decrypt(previous.encrypted_content) if previous else "", decrypt(row.encrypted_content)
        ),
        "previous_id": previous.id if previous else None,
        "current_id": row.id,
    }


@app.post(P + "/jobs", status_code=202)
def start_job(payload: dict, user=Depends(operator), db=Depends(db_session)):
    return svc.serialize(svc.enqueue(db, payload.get("kind"), payload.get("target_id"), user))


@app.post(P + "/jobs/{id}/cancel")
def cancel_job(id: str, user=Depends(operator), db=Depends(db_session)):
    job = svc.get(db, m.Job, id)
    if job.status not in ("queued", "running"):
        raise HTTPException(409, "Görev zaten tamamlanmış")
    job.cancel_requested = True
    if job.status == "queued":
        job.status, job.active_key, job.finished_at = "cancelled", None, now()
    audit(db, user, "cancel", "jobs", id, "Görev iptali istendi")
    db.commit()
    svc.publish()
    return svc.serialize(job)


@app.post(P + "/alerts/{id}/acknowledge")
def acknowledge(id: str, user=Depends(operator), db=Depends(db_session)):
    alert = svc.get(db, m.Alert, id)
    alert.acknowledged_at, alert.acknowledged_by = now(), user.id
    audit(db, user, "acknowledge", "alerts", id, "Alarm görüldü olarak işaretlendi")
    db.commit()
    return svc.serialize(alert)


@app.post(P + "/users/{id}/toggle")
def toggle_user(id: str, user=Depends(admin), db=Depends(db_session)):
    if id == user.id:
        raise HTTPException(409, "Kendi hesabınızı devre dışı bırakamazsınız")
    row = svc.get(db, m.User, id)
    row.is_active = not row.is_active
    db.execute(delete(m.AuthSession).where(m.AuthSession.user_id == id))
    audit(db, user, "toggle_user", "users", id, "Hesap erişimi değiştirildi")
    db.commit()
    return svc.serialize(row)


@app.get(P + "/{resource}")
def list_items(
    resource: str,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", max_length=120),
    device_id: str | None = None,
    user=Depends(current_user),
    db=Depends(db_session),
):
    if resource in ("users", "audit") and user.role != "admin":
        raise HTTPException(403, "Yönetici yetkisi gerekli")
    return svc.list_resource(db, resource, limit, offset, q, device_id)


@app.get(P + "/{resource}/{id}")
def get_item(resource: str, id: str, user=Depends(current_user), db=Depends(db_session)):
    if resource not in svc.RESOURCES:
        raise HTTPException(404, "Kaynak bulunamadı")
    if resource in ("users", "audit") and user.role != "admin":
        raise HTTPException(403, "Yönetici yetkisi gerekli")
    return svc.serialize(svc.get(db, svc.RESOURCES[resource][0], id))


@app.post(P + "/{resource}", status_code=201)
def create_item(resource: str, payload: dict, user=Depends(operator), db=Depends(db_session)):
    return svc.save_resource(db, resource, payload, user)


@app.put(P + "/{resource}/{id}")
def update_item(resource: str, id: str, payload: dict, user=Depends(operator), db=Depends(db_session)):
    return svc.save_resource(db, resource, payload, user, id)


@app.delete(P + "/{resource}/{id}", status_code=204)
def delete_item(resource: str, id: str, user=Depends(admin), db=Depends(db_session)):
    svc.delete_resource(db, resource, id, user)


@app.websocket(P + "/ws")
async def websocket(ws: WebSocket):
    if ws.headers.get("origin") != settings().public_url:
        await ws.close(code=1008)
        return
    with session_factory()() as db:
        user = session_user(db, ws.cookies.get("netrix_session"))
        if not user:
            await ws.close(code=1008)
            return
    await ws.accept()
    sub = None
    try:
        sub = redis_client().pubsub()
        await asyncio.to_thread(sub.subscribe, "netrix:events")
        checked = time.monotonic()
        while True:
            message = await asyncio.to_thread(sub.get_message, ignore_subscribe_messages=True, timeout=1)
            if message:
                await ws.send_json({"type": "refresh"})
            if time.monotonic() - checked > 20:
                with session_factory()() as db:
                    if not session_user(db, ws.cookies.get("netrix_session")):
                        await ws.close(code=1008)
                        return
                await ws.send_json({"type": "heartbeat", "time": now().isoformat()})
                checked = time.monotonic()
            await asyncio.sleep(0.1)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        try:
            await ws.close(code=1013)
        except Exception:
            pass
    finally:
        if sub:
            sub.close()


STATIC = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Uç nokta bulunamadı")
        file = STATIC / path
        if path and file.is_file() and file.resolve().is_relative_to(STATIC.resolve()):
            return FileResponse(file)
        return FileResponse(STATIC / "index.html")
