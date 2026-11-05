"""Bounded, exact SNMP validation when an agent omits VLAN/FID metadata."""

from datetime import datetime, timedelta

from ..core import now
from . import protocols as p

VLAN_EGRESS = "1.3.6.1.2.1.17.7.1.4.3.1.2"


def candidates(hint, mac):
    """SQL is a routing hint only. Never derive a FID from the VLAN number."""
    tables = hint.get("tables", {})
    if hint.get("failed") or set(hint.get("unsupported", ())) & {
        "vlan_fdb_port",
        "vlan_fdb_status",
        "bridge_ifindex",
    }:
        return []
    try:
        at = datetime.fromisoformat(hint["fdb_at"])
        if not now() - timedelta(hours=7) <= at <= now() + timedelta(minutes=1):
            return []
    except (KeyError, TypeError, ValueError):
        return []
    suffix = "." + ".".join(str(int(b, 16)) for b in mac.split(":"))
    fids = set()
    for index in tables.get("vlan_fdb_port", {}):
        fid = index.removesuffix(suffix)
        if index.endswith(suffix) and fid.isdigit() and 0 < int(fid) <= 4294967295:
            fids.add(int(fid))
    if len(fids) > 16:
        raise p.NetworkError("Too many unresolved FID candidates")
    return sorted(fids)


def member(value, bridge):
    """Q-BRIDGE PortList: bridge port 1 is the high bit of the first octet."""
    if not hasattr(value, "asOctets"):
        return False
    raw = value.asOctets()
    index, bit = divmod(bridge - 1, 8)
    return index < len(raw) and bool(raw[index] & (128 >> bit))


async def validate(query, hint, mac, vid, mapping):
    fids = candidates(hint, mac)
    if not fids:
        return None
    suffix = ".".join(str(int(b, 16)) for b in mac.split(":"))
    oids = [
        p.IPAM_TABLES[key] + f".{fid}.{suffix}"
        for fid in fids
        for key in ("vlan_fdb_port", "vlan_fdb_status")
    ]
    values = await query.get(oids)
    found = []
    for fid in fids:
        portoid = p.IPAM_TABLES["vlan_fdb_port"] + f".{fid}.{suffix}"
        statusoid = p.IPAM_TABLES["vlan_fdb_status"] + f".{fid}.{suffix}"
        bridge = p.number(values.get(portoid))
        if str(values.get(statusoid)) not in ("1", "3", "5") or not bridge or not 1 <= bridge <= 65535:
            continue
        # Positive evidence of another/shared VLAN is never bypassed.
        if any(str(v) == str(fid) for v in mapping.values()):
            return None
        found.append((fid, bridge))
    # Independent FIDs cannot be disambiguated using the port VLAN bitmap alone.
    if len(found) > 1:
        raise p.NetworkError("Conflicting live SNMP FID candidates")
    if not found:
        return None
    fid, bridge = found[0]
    vlan_oid = VLAN_EGRESS + "." + str(vid)
    if not member((await query.get([vlan_oid])).get(vlan_oid), bridge):
        return None
    return fid, bridge


async def neighbors(query, tables, name):
    """Refresh neighbor indexes over SNMP; cached absence alone proves no edge port."""
    from .neighbors import local_port, parse_neighbors

    # A walk can be empty because the MIB is hidden/unsupported. Confirm a live
    # protocol scalar before treating an empty neighbor table as absence.
    lldp_clock = "1.0.8802.1.1.2.1.2.1.0"
    cdp_run = "1.3.6.1.4.1.9.9.23.1.3.1.0"
    supported = await query.get([lldp_clock, cdp_run])
    if p.number(supported.get(lldp_clock)) is None and str(supported.get(cdp_run)) != "1":
        raise p.NetworkError("SNMP neighbor protocol not confirmed")
    tables = dict(tables)
    if p.number(supported.get(lldp_clock)) is not None:
        for key in ("lldp_local_id", "lldp_local_type", "lldp_local_desc"):
            tables[key] = await query.metadata(p.IPAM_TABLES[key])
    current = {
        k: dict(v)
        for k, v in tables.items()
        if k.startswith("lldp_local") or k in ("if_name", "if_descr", "if_alias", "if_mac")
    }
    exact = {}
    for protocol, primary in (("lldp", "lldp_chassis"), ("cdp", "cdp_name")):
        rows = await query.metadata(p.IPAM_TABLES[primary])
        for index, value in rows.items():
            parts = index.split(".")
            local = (
                local_port(tables, parts[1])
                if protocol == "lldp" and len(parts) == 3
                else str(tables.get("if_name", {}).get(parts[0], ""))
            )
            if not local or local not in set(tables.get("if_name", {}).values()):
                # Do not silently discard a neighbor whose local port cannot be resolved.
                raise p.NetworkError("Unresolved SNMP neighbor port")
            if local != name:
                continue
            current.setdefault(primary, {})[index] = value
            for key, base in p.IPAM_TABLES.items():
                if key.startswith(protocol + "_") and "local" not in key:
                    exact[base + "." + index] = (key, index)
    if exact:
        for oid, value in (await query.get(exact)).items():
            key, index = exact[oid]
            current.setdefault(key, {})[index] = value
    return parse_neighbors(current)
