"""Offline first materialization from existing observations. Never contacts a device."""

from copy import copy
from datetime import datetime, timedelta

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..services import lock_vrf, publish
from . import pipeline, service
from .connections import Evidence


class StoredSources:
    def __init__(self, row, vlan, obs, evidence):
        self.row, self.vlan, self.obs, self.evidence = row, vlan, obs, evidence
        self.stale_sources = set()

    def age(self, source, value, lifetime):
        at = datetime.fromisoformat(value) if isinstance(value, str) else value
        if at < now() - lifetime:
            self.stale_sources.add(source)

    async def gateway(self, address):
        physical = self.evidence.resolve(self.row, self.vlan)
        for g in physical["gateway_evidence"]:
            self.age(
                "Gateway",
                g["observed_at"],
                timedelta(seconds=max(300, min(self.vlan.discovery_interval * 2, 86400))),
            )
        return {"mac_address": physical["mac_address"], "gateway_evidence": physical["gateway_evidence"]}

    async def vmware(self, address, mac):
        return [
            {
                **o.data,
                "address": o.data.get("guest_address") or o.data.get("host_address") or address,
                "point_match": True,
            }
            for o in self.obs
            if o.source == "vcenter"
            and o.observed_at >= now() - timedelta(hours=24)
            and o.data.get("present", True)
        ]

    async def physical(self, address, mac):
        result = self.evidence.resolve(self.row, self.vlan, identity_mac=mac)
        for c in result["connections"]:
            self.age(
                "Switch/port",
                c["observed_at"],
                timedelta(seconds=max(300, min(self.vlan.discovery_interval * 2, 86400))),
            )
        return result

    async def dhcp(self, address, mac):
        return [
            {**o.data, "address": o.data.get("address") or address}
            for o in self.obs
            if o.source == "windows_dhcp"
            and o.observed_at >= now() - timedelta(hours=24)
            and o.data.get("present", True)
        ]

    async def dns(self, address):
        return service.dns_hostname(self.obs, self.vlan)


async def run():
    count = 0
    with session_factory()() as db:
        ids = list(
            db.scalars(
                select(m.IPAddress.id)
                .outerjoin(m.IPAMResult, m.IPAMResult.address_id == m.IPAddress.id)
                .where(m.IPAMResult.id.is_(None))
                .order_by(m.IPAddress.id)
            )
        )
        vrfs = set(db.scalars(select(m.VLAN.vrf_id)))
        evidence = Evidence(db, vrfs)
        # Preserve last-known attachments on the one-time import, with explicit stale diagnostics.
        # Moving this local clock never changes shared snapshots or claims a new network read.
        evidence = copy(evidence)
        evidence.at = min((s.created_at for s, _ in evidence.snapshots.values()), default=now())
        evidence.static = {}
        evidence.attached = {}
    for start in range(0, len(ids), 100):
        with session_factory()() as db:
            rows = list(db.scalars(select(m.IPAddress).where(m.IPAddress.id.in_(ids[start : start + 100]))))
            vlans = {
                v.id: v for v in db.scalars(select(m.VLAN).where(m.VLAN.id.in_({r.vlan_id for r in rows})))
            }
            obs = service.observations(db, rows)
            legacy = {r["id"]: r for r in service.enrich(db, rows)}
        for row in rows:
            if not vlans[row.vlan_id].cidr:
                continue
            started = now()
            sources = StoredSources(row, vlans[row.vlan_id], obs[row.id], evidence)
            result = await pipeline.resolve(row.address, sources)
            if sources.stale_sources:
                result["status"] = "problem"
                result["issues"].append(
                    {
                        "source": "resolution",
                        "code": "stale_source",
                        "message": "Son doğrulanmış "
                        + ", ".join(sorted(sources.stale_sources))
                        + " bilgileri korunuyor; kaynak gözlemi eski, yeni ağ sorgusu yapılmadı.",
                    }
                )
            for step in result["steps"]:
                step["mode"] = "stored"
            for observation in result["values"].get("observations", []):
                previous = [o.observed_at for o in obs[row.id] if o.source == observation["source"]]
                if observation["source"] == "gateway":
                    previous = [g["observed_at"] for g in result["values"]["gateway_evidence"]]
                    if previous:
                        observation["observed_at"] = max(previous)
                elif previous:
                    observation["observed_at"] = max(previous).isoformat()
            result["values"]["cached_import"] = True
            with session_factory()() as db:
                lock_vrf(db, row.vrf_id)
                current = db.scalar(select(m.IPAddress).where(m.IPAddress.id == row.id).with_for_update())
                # Never overwrite a manual scan or a concurrently completed scheduled result.
                if (
                    not current
                    or [current.address, current.vrf_id, current.vlan_id]
                    != [row.address, row.vrf_id, row.vlan_id]
                    or db.scalar(select(m.IPAMResult.id).where(m.IPAMResult.address_id == row.id))
                ):
                    continue
                previous = {
                    field: legacy[row.id].get(field) for field in pipeline.FIELDS if legacy[row.id].get(field)
                }
                for field in ("hostname", "operating_system"):
                    if legacy[row.id].get("field_sources", {}).get(field) == "manual":
                        previous.pop(field, None)
                gmacs = {g["mac_address"] for g in legacy[row.id].get("gateway_evidence", [])}
                previous["mac_address"] = next(iter(gmacs)) if len(gmacs) == 1 else ""
                seed = m.IPAMResult(
                    address_id=row.id,
                    address_scope=[row.address, row.vrf_id, row.vlan_id],
                    status="problem",
                    values=previous,
                    started_at=started,
                    completed_at=started,
                    issues=[],
                    steps=[],
                    retained=True,
                )
                db.add(seed)
                db.flush()
                pipeline.save_result(db, current, started, result)
                if sources.stale_sources:
                    seed.retained = True
                db.commit()
                count += 1
        for id in vlans:
            publish(ipam_vlan=id)
    return count
