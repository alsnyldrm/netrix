"""Compact, versioned projections of the latest device evidence. No network I/O."""

import ipaddress


def device_rank(device):
    return 3 if device.kind == "backbone_switch" else 2


def identity_rank(observation, devices):
    return {"vcenter": 0, "windows_dhcp": 1, "corner_switch": 2, "backbone_switch": 3, "dns": -1}.get(
        observation.source, 6
    )


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
    for neighbor in evidence.get("neighbors") or []:
        local = neighbor.get("interface_name")
        data = neighbor.get("evidence") or {}
        aggregate = data.get("local_aggregate") or {}
        port = aggregate.get("name") or local
        uplinks.update(v for v in (local, port) if v)
        lldp = data.get("lldp") or {}
        # An AP/server advertising its own MAC is the endpoint, not a transit switch.
        for value in (
            lldp.get("chassis_id") if lldp.get("chassis_subtype") == 4 else None,
            lldp.get("port_id") if lldp.get("port_subtype") == 3 else None,
        ):
            mac = normalized_mac(value)
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
