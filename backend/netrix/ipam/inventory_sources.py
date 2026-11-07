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
