"""Compact, versioned projections of the latest device evidence. No network I/O."""

import ipaddress
import re


def device_rank(device):
    return {"corner_switch": 2, "backbone_switch": 3, "firewall": 4}.get(device.kind, 2)


def identity_rank(observation, devices):
    return {
        "vcenter": 0,
        "windows_dhcp": 1,
        "corner_switch": 2,
        "backbone_switch": 3,
        "firewall": 4,
        "dns": -1,
    }.get(observation.source, 6)


def device_name(config):
    """Physical identity is distinct from the integration's administrative label."""
    name = (config.evidence or {}).get("hostname")
    if name:
        return str(name).strip()
    name = config.name
    suffix = " · " + config.host
    if name.startswith("IPAM · ") and name.endswith(suffix):
        return name[len("IPAM · ") : -len(suffix)]
    return name


def hostname_keys(value):
    value = str(value or "").strip().rstrip(".").casefold()
    if not value or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", value):
        return set()
    try:
        ipaddress.ip_address(value)
        return set()
    except ValueError:
        pass
    return {value, value.split(".")[0]}


def neighbor_names(neighbor):
    data = neighbor.get("evidence") or {}
    lldp, cdp = data.get("lldp") or {}, data.get("cdp") or {}
    values = [neighbor.get("remote_name"), lldp.get("system_name"), cdp.get("system_name")]
    if lldp.get("chassis_subtype") == 7:
        values.append(lldp.get("chassis_id"))
    values.append(cdp.get("device_id"))
    return set().union(*(hostname_keys(value) for value in values))


def project_snapshot(evidence):
    from .service import normalized_mac

    tables = evidence.get("tables") or {}
    macs, arp, hosts, uplinks, neighbor_macs = {}, {}, {}, set(), {}
    bridges = tables.get("bridge_ifindex") or {}
    for table in ("fdb_port", "vlan_fdb_port"):
        for key, bridge in (tables.get(table) or {}).items():
            values = key.split(".")[-6:]
            try:
                if len(values) != 6:
                    continue
                raw = bytes(int(v) for v in values)
                mac = raw.hex(":")
                index = int(bridges[str(bridge)])
                if index > 0:
                    macs.setdefault(mac, set()).add(index)
            except (ValueError, KeyError, TypeError):
                continue
    for key, value in (tables.get("arp_mac") or {}).items():
        parts = key.split(".")
        try:
            address = str(ipaddress.IPv4Address(".".join(parts[-4:])))
            index = int(parts[-5])
        except (ValueError, IndexError):
            continue
        mac = normalized_mac(value)
        if mac:
            arp.setdefault(address, []).append((mac, index))
    for key, value in (tables.get("ndp_mac") or {}).items():
        try:
            parts = [int(v) for v in key.split(".")]
            if (
                len(parts) < 3
                or parts[1] not in (1, 2)
                or parts[2] not in (4, 16)
                or len(parts[3:]) != parts[2]
            ):
                continue
            address = str(ipaddress.ip_address(bytes(parts[3:])))
        except ValueError:
            continue
        mac = normalized_mac(value)
        if mac:
            arp.setdefault(address, []).append((mac, parts[0]))
    chassis_ports, chassis_macs = {}, {}
    for neighbor in evidence.get("neighbors") or []:
        local = neighbor.get("interface_name")
        data = neighbor.get("evidence") or {}
        aggregate = data.get("local_aggregate") or {}
        port = aggregate.get("name") or local
        uplinks.update(v for v in (local, port) if v)
        lldp = data.get("lldp") or {}
        chassis_id = str(lldp.get("chassis_id") or "").lower()
        # UUID chassis IDs identify multiple NICs of one physical server/storage.
        # Generic descriptions and arbitrary local IDs do not prove a shared host.
        chassis = (
            chassis_id
            if lldp.get("chassis_subtype") == 7
            and re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", chassis_id)
            else None
        )
        if chassis and local:
            chassis_ports.setdefault(chassis, set()).add(local)
        # An AP/server advertising its own MAC is the endpoint, not a transit switch.
        for value in (
            lldp.get("chassis_id") if lldp.get("chassis_subtype") == 4 else None,
            lldp.get("port_id") if lldp.get("port_subtype") == 3 else None,
        ):
            mac = normalized_mac(value)
            if mac and chassis:
                chassis_macs.setdefault(chassis, set()).add(mac)
            if mac and port:
                neighbor_macs[(mac, port)] = {"name": neighbor.get("remote_name") or "", "members": []}
        # A neighbor's management IP proves the endpoint of a port/aggregate.
        # Chassis MACs are NOT substituted for the IP's MAC (bonds can differ).
        for protocol in ("lldp", "cdp"):
            address = (data.get(protocol) or {}).get("management_address")
            try:
                address = str(ipaddress.ip_address(address))
            except ValueError:
                continue
            if port:
                key = (address, port)
                item = hosts.setdefault(key, {"name": neighbor.get("remote_name") or "", "members": set()})
                if local and aggregate.get("name"):
                    item["members"].add(local)
    for chassis, member_ports in chassis_ports.items():
        for mac in chassis_macs.get(chassis, ()):
            for port in member_ports:
                neighbor_macs.setdefault((mac, port), {"name": "", "members": []})
    detail = evidence.get("neighbor_detail") or {}
    for member, aggregate in (detail.get("trunks") or {}).items():
        if member in uplinks and aggregate.get("name"):
            uplinks.add(aggregate["name"])
    root = (detail.get("spanning_tree") or {}).get("port")
    if root:
        uplinks.add(root)
    return {
        "macs": {mac: tuple(sorted(indices)) for mac, indices in macs.items()},
        "arp": arp,
        "neighbor_macs": neighbor_macs,
        "hosts": {key: {**value, "members": sorted(value["members"])} for key, value in hosts.items()},
        "uplinks": uplinks,
    }
