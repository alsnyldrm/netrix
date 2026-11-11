"""Delete an unmanaged IP only after a successful scheduled absence check."""

import ipaddress
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select

from .. import models as m
from ..core import now
from ..identity.audit import record
from ..services import lock_vrf
from .connections import gateway_interfaces
from .mac_cache import is_switch


def complete_sources(context, vlan, started):
    if context.errors or not context.gateway_evidence or not context.switch_evidence:
        return False
    network = ipaddress.ip_network(vlan.cidr)
    gateways = {
        id
        for id, d in context.base.devices.items()
        if (d.is_gateway or d.kind in ("router", "firewall")) and not is_switch(d)
    }
    attached = False
    for id in gateways:
        snapshot = context.gateway_evidence.snapshots.get(id)
        if not snapshot:
            return False
        observed, projection = snapshot
        data = projection["evidence"]
        if observed.created_at < started or data.get("failed"):
            return False
        if gateway_interfaces(projection["tables"], network):
            tables = ("arp_mac", "ndp_mac") if network.version == 4 else ("ndp_mac",)
            if not any(
                (read := data.get("table_reads", {}).get(name, {})).get("status") == "complete"
                and read.get("attempted_at")
                and datetime.fromisoformat(read["attempted_at"]) >= started
                for name in tables
            ):
                return False
            attached = True
    evidence = context.switch_evidence
    switches = {id for id, d in evidence.devices.items() if is_switch(d)}
    cutoff = now() - timedelta(seconds=max(300, min(vlan.discovery_interval * 2, 86400)))
    states = {state.device_id: state for state in evidence.state_rows}
    return (
        attached
        and bool(switches)
        and all(
            id in evidence.snapshots
            and (state := states.get(id)) is not None
            and state.healthy
            and state.fdb_complete
            and state.fdb_at
            and state.fdb_at >= cutoff
            and state.neighbors_at
            and state.neighbors_at >= cutoff
            and (state.lldp_complete or state.cdp_complete)
            for id in switches
        )
    )


def delete_if_absent(db, row, vlan, started):
    """Recheck current evidence and user ownership while holding the IP lock."""
    lock_vrf(db, row.vrf_id)
    row = db.scalar(
        select(m.IPAddress)
        .where(m.IPAddress.id == row.id)
        .with_for_update(of=m.IPAddress)
        .execution_options(populate_existing=True)
    )
    if not row or row.vlan_id != vlan.id or row.vrf_id != vlan.vrf_id or row.updated_at > started:
        return False
    if row.status != "active" or any(
        getattr(row, field)
        for field in (
            "hostname",
            "mac_address",
            "operating_system",
            "device_id",
            "interface_id",
            "institution_id",
            "site_id",
            "sub_site_id",
            "cabinet",
            "location",
            "is_gateway",
            "nic_teaming",
        )
    ):
        return False
    if db.scalar(
        select(m.Audit.id)
        .where(
            m.Audit.entity_type == "addresses",
            m.Audit.entity_id == row.id,
            m.Audit.action.in_(("create", "update")),
        )
        .limit(1)
    ) or db.scalar(
        select(m.Job.id)
        .where(
            m.Job.target_id == row.id,
            m.Job.active_key.is_not(None),
        )
        .limit(1)
    ):
        return False

    ping = db.scalar(select(m.PingState).where(m.PingState.address_id == row.id))
    if not ping or ping.reachability != "no_reply":
        return False
    if (
        db.scalar(
            select(m.GatewayBinding.id)
            .where(
                m.GatewayBinding.address == row.address,
                m.GatewayBinding.vrf_id == row.vrf_id,
                m.GatewayBinding.present.is_(True),
                m.GatewayBinding.device_id.is_not(None),
            )
            .limit(1)
        )
        or db.scalar(
            select(m.DHCPBinding.id)
            .where(
                m.DHCPBinding.address == row.address,
                m.DHCPBinding.present.is_(True),
            )
            .limit(1)
        )
        or db.scalar(
            select(m.VMwareAddress.id)
            .where(
                m.VMwareAddress.address == row.address,
                m.VMwareAddress.present.is_(True),
            )
            .limit(1)
        )
        or db.scalar(
            select(m.DNSRecord.id)
            .where(
                m.DNSRecord.address_id == row.id,
                m.DNSRecord.hostname != "",
                m.DNSRecord.updated_at >= started,
            )
            .limit(1)
        )
    ):
        return False

    previous = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == row.id))
    if previous and previous.started_at > started:
        return False
    macs = set(
        db.scalars(
            select(m.GatewayBinding.mac_address).where(
                m.GatewayBinding.address == row.address, m.GatewayBinding.vrf_id == row.vrf_id
            )
        )
    )
    if previous and previous.address_scope == [row.address, row.vrf_id, row.vlan_id]:
        macs.add(previous.values.get("mac_address"))
    macs -= {"", None}
    # Without a known MAC, a MAC-only inventory record cannot be ruled out.
    if not macs:
        return False

    def compact(column):
        return func.lower(func.replace(func.replace(func.replace(column, ":", ""), "-", ""), " ", ""))

    compact_macs = {mac.replace(":", "") for mac in macs}
    if db.scalar(
        select(m.Link.id)
        .join(m.Device, m.Device.id == m.Link.device_id)
        .outerjoin(m.LLDPNeighbor, m.LLDPNeighbor.link_id == m.Link.id)
        .outerjoin(m.CDPNeighbor, m.CDPNeighbor.link_id == m.Link.id)
        .where(
            m.Device.vrf_id == row.vrf_id,
            m.Link.is_current.is_(True),
            or_(
                m.LLDPNeighbor.management_address == row.address,
                m.CDPNeighbor.management_address == row.address,
                compact(m.LLDPNeighbor.chassis_id).in_(compact_macs),
                compact(m.CDPNeighbor.device_id).in_(compact_macs),
            ),
        )
        .limit(1)
    ):
        return False
    # Even transit, ambiguous and otherwise rejected FDB hits veto deletion.
    if db.scalar(
        select(m.SwitchMacEntry.id)
        .where(
            m.SwitchMacEntry.vrf_id == row.vrf_id,
            m.SwitchMacEntry.vlan_vid.in_((0, vlan.vid)),
            m.SwitchMacEntry.mac_address.in_(macs),
            m.SwitchMacEntry.present.is_(True),
        )
        .limit(1)
    ):
        return False
    record(
        db, None, "delete", "addresses", row.id, f"Kaynaklarda artık bulunmayan keşif IP'si: {row.address}"
    )
    db.delete(row)
    return True
