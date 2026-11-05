"""FDB rows written by group scans; read-only fallback to primary IPAM evidence."""

from datetime import timedelta

from sqlalchemy import select, tuple_
from sqlalchemy.orm import load_only

from .. import models as m
from ..core import now
from .connections import Evidence, Snapshot, projections

# Group scans are the only collector; a daily group plus margin stays usable all day.
FRESHNESS = timedelta(hours=25)
REQUIRED = {"vlan_fdb_port", "vlan_fdb_status", "bridge_ifindex"}


def is_switch(device):
    return device.kind not in {"router", "firewall"} and (
        device.kind == "switch"
        or device.device_type.name.casefold()
        in {"switch", "backbone", "backbone switch", "corner switch", "san switch"}
    )


def context(device, profile):
    from .network import read_context

    return read_context(device, profile, None)


def accepted_contexts(db, device, profile):
    """Group scans record the SSH profile of switches they also read over SSH."""
    from .network import detail_profile, read_context

    return (context(device, profile), read_context(device, profile, detail_profile(db, device)))


def save_snapshot(db, device, profile, job_id, evidence, *, error=""):
    """Diff current rows in one transaction; failed/partial reads never retire old bindings."""
    state = db.scalar(
        select(m.SwitchMacSnapshot).where(m.SwitchMacSnapshot.device_id == device.id).with_for_update()
    )
    if state is None:
        state = m.SwitchMacSnapshot(device_id=device.id)
        db.add(state)
        db.flush()
    state.address = device.management_ip
    state.job_id, state.attempted_at = job_id, now()
    incomplete = (
        (REQUIRED | {"if_status"}) & set(evidence.get("unsupported") or [])
        or not REQUIRED <= (evidence.get("tables") or {}).keys()
        or not evidence.get("interfaces")
        or {"if_name", "if_descr"} <= set(evidence.get("unsupported") or [])
    )
    if error or evidence.get("failed") or incomplete:
        # Persist read diagnostics and valid positive rows; never retire previous facts.
        from ..sources.network import write

        write(db, state, {**evidence, "failed": bool(error or evidence.get("failed"))}, now())
        state.healthy = False
        state.error_class = error or ("IncompleteFDB" if incomplete else "SourceFailed")
        db.flush()
        return {"read": 0, "failed": 1, "added": 0, "removed": 0, "error_class": state.error_class}
    existing = {(e.fdb_id, e.mac_address, e.port) for e in state.mac_entries if e.present}
    state.observed_at, state.healthy, state.error_class = now(), True, ""
    state.read_context = context(device, profile)
    state.evidence = evidence
    db.flush()
    current = {(e.fdb_id, e.mac_address, e.port) for e in state.mac_entries if e.present}
    added, removed = len(current - existing), len(existing - current)
    if any(r.name in REQUIRED and r.status != "complete" for r in state.unsupported):
        state.healthy, state.error_class = False, "IncompleteFDB"
        db.flush()
        return {"read": 0, "failed": 1, "added": added, "removed": 0, "error_class": state.error_class}
    if added or removed:
        db.add(
            m.Event(
                device_id=device.id,
                kind="switch_mac_change",
                message=f"{device.name}: switch MAC tablosu güncellendi",
                details={"added": added, "removed": removed},
            )
        )
    db.flush()
    return {"read": 1, "failed": 0, "added": added, "removed": removed}


class CachedEvidence(Evidence):
    def _static_links(self, vrf_id, cutoff):
        return super()._static_links(vrf_id, self.at - FRESHNESS)


def fallback(db, rows, items, prefixes, primary, *, scoped=None):
    """One indexed bulk lookup, only for rows without any primary/manual/VM attachment."""
    eligible = {}
    for row, item in zip(rows, items):
        macs = {g["mac_address"] for g in item.get("gateway_evidence", [])}
        if (
            len(macs) != 1
            or item.get("mac_conflict")
            or item.get("gateway_mac_conflict")
            or item.get("connection_ambiguous")
            or item.get("connected_device")
            or item.get("connected_port")
            or item.get("connections")
            or item.get("connection_type") == "vcenter"
            or item.get("manual_connection")
        ):
            continue
        eligible[row.id] = (row.vrf_id, prefixes[row.vlan_id].vid, next(iter(macs)))
    if not eligible:
        return items
    pairs, ids = list(set(eligible.values())), set()
    for start in range(0, len(pairs), 250):
        ids.update(
            db.scalars(
                select(m.SwitchMacEntry.snapshot_id).where(
                    tuple_(
                        m.SwitchMacEntry.vrf_id, m.SwitchMacEntry.vlan_vid, m.SwitchMacEntry.mac_address
                    ).in_(pairs[start : start + 250])
                )
            )
        )
    states = (
        list(
            db.scalars(
                select(m.SwitchMacSnapshot)
                .options(
                    load_only(
                        m.SwitchMacSnapshot.id,
                        m.SwitchMacSnapshot.device_id,
                        m.SwitchMacSnapshot.observed_at,
                        m.SwitchMacSnapshot.updated_at,
                    )
                )
                .where(
                    m.SwitchMacSnapshot.id.in_(ids),
                    m.SwitchMacSnapshot.healthy.is_(True),
                    m.SwitchMacSnapshot.observed_at >= primary.at - FRESHNESS,
                )
            )
        )
        if ids
        else []
    )
    profiles = (
        {
            p.id: p
            for p in db.scalars(
                select(m.Credential)
                .options(load_only(m.Credential.id, m.Credential.updated_at))
                .where(
                    m.Credential.id.in_(
                        {
                            primary.devices[s.device_id].snmp_credential_id
                            for s in states
                            if s.device_id in primary.devices
                        }
                    )
                )
            )
        }
        if states
        else {}
    )
    valid = []
    for state in states:
        device = primary.devices.get(state.device_id)
        profile = profiles.get(device.snmp_credential_id) if device else None
        if (
            device
            and profile
            and device.lifecycle_status == "active"
            and is_switch(device)
            and state.read_context in accepted_contexts(db, device, profile)
        ):
            valid.append(state)
    if not valid:
        return items
    cached = CachedEvidence.__new__(CachedEvidence)
    cached.__dict__.update(primary.__dict__)
    cached.static, cached.attached = {}, {}
    cached.snapshots = {
        s.device_id: (Snapshot(s.id, s.observed_at), p)
        for s, p in projections(db, valid, model=m.SwitchMacSnapshot)
    }
    cached.links = [l for l in primary.links if l.device_id in cached.snapshots]
    cached.raw_neighbors, cached.excluded_raw_neighbors = {}, {}
    cached.refresh_neighbors()
    for row, item in zip(rows, items):
        if row.id not in eligible:
            continue
        resolver = cached
        address_primary = (scoped or {}).get(row.id)
        if address_primary:
            # A new one-IP read (including an empty/failed source) supersedes
            # older cached positives for that source, only for this address.
            snapshots = {
                id: value
                for id, value in cached.snapshots.items()
                if id not in address_primary.snapshots
                or value[0].created_at > address_primary.snapshots[id][0].created_at
            }
            if not snapshots:
                continue
            resolver = CachedEvidence.__new__(CachedEvidence)
            resolver.__dict__.update(cached.__dict__)
            resolver.snapshots = snapshots
            resolver.links = [l for l in cached.links if l.device_id in snapshots]
            resolver.static, resolver.attached = {}, {}
            resolver.raw_neighbors, resolver.excluded_raw_neighbors = {}, {}
            resolver.refresh_neighbors()
        proof = resolver.resolve(
            row, prefixes[row.vlan_id], identity_mac=eligible[row.id][2], identity_source="switch_mac_cache"
        )
        if not proof["connections"]:
            continue
        for candidate in proof["connections"]:
            candidate["primary_source"] = candidate["source"]
            candidate["source"] = "switch_mac_cache"
        for key in (
            "connections",
            "connection_groups",
            "connected_device",
            "connected_port",
            "connection_type",
            "connection_ambiguous",
            "connection_reason",
        ):
            item[key] = proof[key]
        item["connection_type"] = "switch_mac_cache" if proof["connected_device"] else ""
        item["sources"] = sorted(set(item["sources"]) | {"switch_mac_cache"})
    return items
