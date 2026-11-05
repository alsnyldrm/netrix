"""Persist only the facts returned by an explicitly requested single-IP query."""

from sqlalchemy import select

from .. import models as m
from ..core import now
from . import neighbors, network, records


@records.source_write
def gateway(db, iprow, device, macs):
    at = now()
    found = set(macs)
    for mac in found:
        records.gateway(db, iprow, {"device_id": device.id, "mac_address": mac}, at)
    for fact in db.scalars(
        select(m.GatewayBinding).where(
            m.GatewayBinding.device_id == device.id,
            m.GatewayBinding.vrf_id == iprow.vrf_id,
            m.GatewayBinding.address == iprow.address,
        )
    ):
        if fact.mac_address not in found:
            fact.present = False


@records.source_write
def switch(db, device, vlan, mac, ports, peers, *, absence_confirmed=False):
    from ..discovery.links import legacy_match

    at = now()
    state = network.state_for(db, device.id, device.management_ip)
    state.observed_at = max(state.observed_at, at) if state.observed_at else at
    state.updated_at = at
    mappings = [v.fdb_id for v in state.vlan_fdbs if v.vlan_vid == vlan.vid]
    default_fid = mappings[0] if len(mappings) == 1 else 0
    found = set()
    for item in ports:
        fid = item.get("fdb_id", default_fid)
        port = network.port_for(state, item["port"], item.get("if_index"))
        fact = next(
            (
                e
                for e in state.mac_entries
                if e.mac_address == mac and e.fdb_id == fid and e.port == port.name
            ),
            None,
        )
        if not fact:
            fact = m.SwitchMacEntry(
                id=m.uid(),
                vrf_id=device.vrf_id,
                vlan_vid=0 if item.get("vlan_unmapped") else vlan.vid,
                fdb_id=fid,
                mac_address=mac,
                port=port.name,
            )
            state.mac_entries.append(fact)
        fact.if_index = item.get("if_index") or 0
        fact.bridge_port = item.get("bridge_port") or next(
            (b.bridge_port for b in state.bridge_ports if b.if_index == fact.if_index), 0
        )
        if item.get("vlan_unmapped"):
            fact.vlan_vid = 0
        fact.status, fact.observed_at, fact.present = "3", at, True
        found.add(fact.id)
    for fact in state.mac_entries:
        if (
            absence_confirmed
            and fact.mac_address == mac
            and fact.vlan_vid == vlan.vid
            and fact.id not in found
        ):
            fact.present = False
    links = list(db.scalars(select(m.Link).where(m.Link.device_id == device.id)))
    for peer in peers:
        candidate = next((l for l in links if legacy_match(l, peer)), None)
        if candidate and (candidate.auto_add_excluded or candidate.source == "manual"):
            continue
        if not candidate:
            candidate = m.Link(id=m.uid(), device_id=device.id)
            db.add(candidate)
            links.append(candidate)
        candidate.interface_name, candidate.remote_name, candidate.remote_port = (
            peer["interface_name"],
            peer.get("remote_name", ""),
            peer.get("remote_port", ""),
        )
        candidate.source, candidate.evidence = peer.get("source", "lldp"), peer.get("evidence") or {}
        candidate.last_seen_at, candidate.is_current = at, True
        neighbors.write(db, candidate)
