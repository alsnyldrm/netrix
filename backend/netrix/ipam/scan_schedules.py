"""Calendar-based full scans; a due slot and its durable VLAN jobs commit together."""

from calendar import monthrange
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .. import models as m
from ..core import now, session_factory
from ..identity.security import audit
from ..services import enqueue, get, publish, serialize

TIMING = ("frequency", "repeat_every", "start_at", "timezone", "run_limit")


def occurrence(group, index):
    start = group.start_at.astimezone(ZoneInfo(group.timezone))
    if group.frequency == "monthly":
        month = start.year * 12 + start.month - 1 + group.repeat_every * index
        year, month = divmod(month, 12)
        month += 1
        value = start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))
    else:
        value = start + timedelta(days=group.repeat_every * index * (7 if group.frequency == "weekly" else 1))
    return value.astimezone(UTC)


def next_after(group, at):
    start, local = (
        group.start_at.astimezone(ZoneInfo(group.timezone)),
        at.astimezone(ZoneInfo(group.timezone)),
    )
    if group.frequency == "monthly":
        index = max(0, ((local.year - start.year) * 12 + local.month - start.month) // group.repeat_every)
    else:
        days = group.repeat_every * (7 if group.frequency == "weekly" else 1)
        index = max(0, (local.date() - start.date()).days // days)
    while occurrence(group, index) <= at:
        index += 1
    return occurrence(group, index)


def catalog(db):
    groups = list(db.scalars(select(m.IPAMScanGroup).order_by(m.IPAMScanGroup.name)))
    members = list(db.execute(select(m.IPAMScanMember.group_id, m.IPAMScanMember.vlan_id)))
    owner = {vlan: group for group, vlan in members}
    return {
        "items": [
            {**serialize(g), "vlan_ids": [vlan for group, vlan in members if group == g.id]} for g in groups
        ],
        "vlans": [
            {"id": id, "vid": vid, "name": name, "cidr": cidr, "vrf": vrf, "group_id": owner.get(id)}
            for id, vid, name, cidr, vrf in db.execute(
                select(m.VLAN.id, m.VLAN.vid, m.VLAN.name, m.VLAN.cidr, m.VRF.name)
                .outerjoin(m.VRF, m.VRF.id == m.VLAN.vrf_id)
                .order_by(m.VLAN.vid, m.VLAN.name)
            )
        ],
    }


def save(db, payload, user, id=None):
    row = m.IPAMScanGroup(run_count=0, generation=0)
    if id:
        row = db.scalar(select(m.IPAMScanGroup).where(m.IPAMScanGroup.id == id).with_for_update())
        if not row:
            raise HTTPException(404, "Tarama grubu bulunamadı")
    ids = sorted(set(payload.vlan_ids))
    vlans = list(db.scalars(select(m.VLAN).where(m.VLAN.id.in_(ids))))
    if len(vlans) != len(ids) or any(not v.cidr for v in vlans):
        raise HTTPException(422, "Seçilen VLAN'ların tümünde geçerli bir IP bloğu olmalı")
    conflict = db.scalar(
        select(m.IPAMScanMember.vlan_id)
        .where(m.IPAMScanMember.vlan_id.in_(ids), m.IPAMScanMember.group_id != (id or ""))
        .limit(1)
    )
    if conflict:
        raise HTTPException(409, "Seçilen VLAN başka bir tarama grubunda. Önce o gruptan çıkarın.")
    data = payload.model_dump(exclude={"vlan_ids"})
    changed = not id or any(getattr(row, k) != data[k] for k in TIMING)
    for key, value in data.items():
        setattr(row, key, value)
    if changed:
        row.generation += 1
        row.run_count = 0
        row.next_run_at = row.start_at
    elif row.enabled and row.next_run_at is None and (not row.run_limit or row.run_count < row.run_limit):
        row.next_run_at = next_after(row, now())
    db.add(row)
    try:
        db.flush()
        db.execute(delete(m.IPAMScanMember).where(m.IPAMScanMember.group_id == row.id))
        db.add_all([m.IPAMScanMember(group_id=row.id, vlan_id=vlan) for vlan in ids])
        audit(
            db,
            user,
            "update" if id else "create",
            "ipam_scan_groups",
            row.id,
            "VLAN tam tarama grubu kaydedildi",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Grup adı veya VLAN üyeliği başka bir kayıtla çakışıyor; listeyi yenileyin"
        ) from None
    publish()
    return {**serialize(row), "vlan_ids": ids}


def remove(db, id, user):
    row = db.scalar(select(m.IPAMScanGroup).where(m.IPAMScanGroup.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Tarama grubu bulunamadı")
    audit(
        db, user, "delete", "ipam_scan_groups", id, "Tarama grubu silindi; VLAN'lar ve mevcut işler korundu"
    )
    db.execute(delete(m.IPAMScanMember).where(m.IPAMScanMember.group_id == id))
    db.execute(delete(m.IPAMScanRun).where(m.IPAMScanRun.group_id == id))
    db.delete(row)
    db.commit()
    publish()


def history(db, id):
    get(db, m.IPAMScanGroup, id)
    rows = list(
        db.scalars(
            select(m.IPAMScanRun)
            .where(m.IPAMScanRun.group_id == id)
            .order_by(m.IPAMScanRun.created_at.desc())
            .limit(20)
        )
    )
    ids = {j["job_id"] for r in rows for j in r.jobs}
    jobs = {j.id: j for j in db.scalars(select(m.Job).where(m.Job.id.in_(ids)))}
    return {
        "items": [
            {
                **serialize(r),
                "jobs": [
                    {**j, "status": jobs[j["job_id"]].status if j["job_id"] in jobs else "removed"}
                    for j in r.jobs
                ],
            }
            for r in rows
        ]
    }


def dispatch_due(at=None):
    """Catch up once after downtime, then advance past missed slots without bursts."""
    at = at or now()
    with session_factory()() as db:
        due_ids = list(
            db.scalars(
                select(m.IPAMScanGroup.id)
                .where(m.IPAMScanGroup.enabled.is_(True), m.IPAMScanGroup.next_run_at <= at)
                .order_by(m.IPAMScanGroup.next_run_at)
                .limit(100)
            )
        )
    for id in due_ids:
        with session_factory()() as db:
            group = db.scalar(select(m.IPAMScanGroup).where(m.IPAMScanGroup.id == id).with_for_update())
            if not group or not group.enabled or not group.next_run_at or group.next_run_at > at:
                continue
            if group.run_limit and group.run_count >= group.run_limit:
                group.next_run_at = None
                db.commit()
                continue
            run = m.IPAMScanRun(
                group_id=id, generation=group.generation, scheduled_for=group.next_run_at, jobs=[], errors=[]
            )
            ids = list(
                db.scalars(
                    select(m.IPAMScanMember.vlan_id)
                    .where(m.IPAMScanMember.group_id == id)
                    .order_by(m.IPAMScanMember.vlan_id)
                )
            )
            jobs, errors = [], []
            for vlan_id in ids:
                try:
                    with db.begin_nested():
                        job = enqueue(db, "ipam_discover", vlan_id, commit=False)
                        vlan = db.get(m.VLAN, vlan_id)
                        jobs.append(
                            {
                                "vlan_id": vlan_id,
                                "job_id": job.id,
                                "vlan_label": f"VLAN-{vlan.vid} / {vlan.name}",
                            }
                        )
                except HTTPException as exc:
                    errors.append({"vlan_id": vlan_id, "message": str(exc.detail)})
            if not ids:
                errors.append({"message": "Grupta VLAN kalmadı; zamanlama durduruldu"})
                group.enabled = False
            run.jobs, run.errors = jobs, errors
            db.add(run)
            group.run_count += 1
            group.last_run_at = at
            group.next_run_at = (
                None
                if not ids or (group.run_limit and group.run_count >= group.run_limit)
                else next_after(group, at)
            )
            db.commit()
    if due_ids:
        publish()
