"""Keep materialized fallback attachments in sync with scheduled MAC snapshots."""

from copy import deepcopy
from datetime import datetime, timedelta

from sqlalchemy import select

from .. import models as m
from ..core import now
from ..services import lock_vrf
from .connections import Evidence
from .mac_cache import fallback


def derived(value):
    return bool(value.get("connections")) and all(
        c.get("source") == "switch_mac_cache" for c in value["connections"]
    )


def identity_current(result, vlan):
    if any(
        i["source"] in ("gateway", "vmware") or i["code"] in ("ambiguous", "owner_conflict")
        for i in result.issues
    ):
        return False
    cutoff = now() - timedelta(seconds=max(300, min(vlan.discovery_interval * 2, 86400)))
    gateway = result.values.get("gateway_evidence", [])
    return bool(gateway) and all(datetime.fromisoformat(g["observed_at"]) >= cutoff for g in gateway)


def eligible(row, result, vlan):
    if not row or not result or not vlan:
        return False
    v = result.values
    if (
        result.address_scope != [row.address, row.vrf_id, row.vlan_id]
        or row.device_id
        or v.get("connection_type") in ("vcenter", "vcenter_host")
    ):
        return False
    if (v.get("connected_device") or v.get("connections")) and not derived(v):
        return False
    return derived(v) or identity_current(result, vlan)


def refresh(db, device_id):
    # Indexed FDB match plus existing cache-derived locations (including removed MACs).
    ids = set(
        db.scalars(
            select(m.IPAMResult.address_id)
            .join(m.IPAddress, m.IPAddress.id == m.IPAMResult.address_id)
            .join(m.VLAN, m.VLAN.id == m.IPAddress.vlan_id)
            .join(
                m.SwitchMacEntry,
                (m.SwitchMacEntry.vrf_id == m.IPAddress.vrf_id)
                & (m.SwitchMacEntry.vlan_vid == m.VLAN.vid)
                & (m.SwitchMacEntry.mac_address == m.IPAMResult.values["mac_address"].as_string()),
            )
            .join(m.SwitchMacSnapshot, m.SwitchMacSnapshot.id == m.SwitchMacEntry.snapshot_id)
            .where(m.SwitchMacSnapshot.device_id == device_id, m.SwitchMacSnapshot.healthy.is_(True))
            .distinct()
        )
    )
    ids.update(
        db.scalars(
            select(m.IPAMResult.address_id).where(
                m.IPAMResult.values["connections"].as_string().like("%switch_mac_cache%"),
                m.IPAMResult.values["connections"].as_string().like("%" + device_id + "%"),
            )
        )
    )
    ids = list(ids)
    changed = 0
    for start in range(0, len(ids), 25):
        rows = list(db.scalars(select(m.IPAddress).where(m.IPAddress.id.in_(ids[start : start + 25]))))
        results = {
            r.address_id: r
            for r in db.scalars(select(m.IPAMResult).where(m.IPAMResult.address_id.in_([r.id for r in rows])))
        }
        vlans = {v.id: v for v in db.scalars(select(m.VLAN).where(m.VLAN.id.in_({r.vlan_id for r in rows})))}
        candidates = [r for r in rows if eligible(r, results.get(r.id), vlans.get(r.vlan_id))]
        if not candidates:
            continue
        evidence = Evidence(db, {r.vrf_id for r in candidates})
        for row in candidates:
            scope = [row.address, row.vrf_id, row.vlan_id]
            lock_vrf(db, scope[1])
            result = db.scalar(
                select(m.IPAMResult)
                .where(m.IPAMResult.address_id == row.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            current = db.scalar(
                select(m.IPAddress)
                .where(m.IPAddress.id == row.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                not current
                or [current.address, current.vrf_id, current.vlan_id] != scope
                or not eligible(current, result, vlans.get(current.vlan_id))
            ):
                continue
            state = db.scalar(select(m.SwitchMacSnapshot).where(m.SwitchMacSnapshot.device_id == device_id))
            at = (state.observed_at if state.healthy else state.attempted_at) if state else None
            if not at or (not result.values.get("cached_import") and at < result.completed_at):
                continue
            before = deepcopy(result.values)
            item = {
                **deepcopy(before),
                "sources": [],
                "connections": [],
                "connection_groups": [],
                "connected_device": "",
                "connected_port": "",
                "connection_type": "",
            }
            proof = (
                fallback(db, [current], [item], vlans, evidence)[0]
                if state.healthy and identity_current(result, vlans[current.vlan_id])
                else {}
            )
            if not proof.get("connected_device") or proof.get("connection_ambiguous"):
                if derived(before):
                    result.status = "problem"
                    result.retained = True
                    result.issues = [i for i in result.issues if i["code"] != "cache_attachment"] + [
                        {
                            "source": "switch",
                            "code": "cache_attachment",
                            "message": "Yeni switch MAC tablosu veya gateway kimliği önceki bağlantıyı doğrulamıyor; son bilinen port korundu.",
                        }
                    ]
                    result.steps = [
                        *result.steps[-31:],
                        {
                            "source": "switch",
                            "device": "Switch MAC tablosu",
                            "status": "ok" if state.healthy else "error",
                            "at": now().isoformat(),
                        },
                    ]
                    result.completed_at = now()
                    changed += 1
                continue
            result.values = {
                **before,
                **{
                    k: proof[k]
                    for k in (
                        "connections",
                        "connection_groups",
                        "connected_device",
                        "connected_port",
                        "connection_type",
                    )
                },
            }
            result.issues = [
                i
                for i in result.issues
                if i["code"] not in ("attachment_missing", "stale_source", "cache_attachment")
            ]
            result.steps = [
                *result.steps[-31:],
                {"source": "switch", "device": "Switch MAC tablosu", "status": "ok", "at": now().isoformat()},
            ]
            result.completed_at = now()
            result.status = "problem" if result.issues else "success"
            if result.status == "success":
                result.last_success_at = result.completed_at
                result.retained = False
            changed += 1
        # Do not hold the VRF lock across the whole cache sweep.
        db.commit()
    return changed
