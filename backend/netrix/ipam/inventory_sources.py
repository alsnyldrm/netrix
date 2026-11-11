"""Read-only service for IPAM to consume inventory MAC-port and neighbor facts."""

from .connections import Evidence


def attachment(db, row, vlan, mac, *, evidence=None):
    evidence = evidence if evidence is not None else Evidence(db, {row.vrf_id})
    result = evidence.resolve(row, vlan, identity_mac=mac)
    gateway_macs = {g["mac_address"] for g in result.get("gateway_evidence", [])}
    if not result["connections"] and not result["connection_ambiguous"] and gateway_macs == {mac}:
        from .mac_cache import fallback

        result.setdefault("sources", [])
        result = fallback(db, [row], [result], {vlan.id: vlan}, evidence)[0]
    return result


def point_evidence(db, row, vlan, mac):
    """Use indexed positive candidates; multi-MAC ports cannot prove an FDB edge.

    Keep every matching protocol peer and every eligible edge, including ambiguous
    alternatives. Full port populations and uplink checks still run for those states.
    """
    from sqlalchemy import exists, func, or_, select
    from sqlalchemy.orm import aliased

    from .. import models as m

    target, other = aliased(m.SwitchMacEntry), aliased(m.SwitchMacEntry)
    states = set(
        db.scalars(
            select(target.snapshot_id).where(
                target.vrf_id == row.vrf_id,
                target.vlan_vid.in_((vlan.vid, 0)),
                target.mac_address == mac,
                target.present.is_(True),
                ~exists(
                    select(other.id).where(
                        other.snapshot_id == target.snapshot_id,
                        other.port == target.port,
                        other.mac_address != target.mac_address,
                        other.present.is_(True),
                        other.status.in_(("1", "3", "5")),
                    )
                ),
            )
        )
    )
    devices = set(db.scalars(select(m.IPAMNetworkState.device_id).where(m.IPAMNetworkState.id.in_(states))))
    devices.update(
        db.scalars(
            select(m.GatewayBinding.device_id).where(
                m.GatewayBinding.vrf_id == row.vrf_id,
                m.GatewayBinding.address == row.address,
                m.GatewayBinding.mac_address == mac,
                m.GatewayBinding.present.is_(True),
            )
        )
    )

    def normalized(column):
        return func.lower(func.replace(func.replace(func.replace(column, ":", ""), "-", ""), " ", ""))

    devices.update(
        db.scalars(
            select(m.Link.device_id)
            .outerjoin(m.LLDPNeighbor, m.LLDPNeighbor.link_id == m.Link.id)
            .outerjoin(m.CDPNeighbor, m.CDPNeighbor.link_id == m.Link.id)
            .where(
                or_(
                    m.LLDPNeighbor.management_address == row.address,
                    m.CDPNeighbor.management_address == row.address,
                    *(
                        normalized(c) == mac.replace(":", "")
                        for c in (
                            m.LLDPNeighbor.chassis_id,
                            m.LLDPNeighbor.port_id,
                            m.CDPNeighbor.device_id,
                            m.CDPNeighbor.port_id,
                        )
                        if mac
                    ),
                )
            )
        )
    )
    return Evidence(db, {row.vrf_id}, source_devices=devices)
