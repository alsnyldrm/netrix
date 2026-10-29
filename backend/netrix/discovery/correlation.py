"""Evidence-based port candidates. Multiple FDB locations remain ambiguous."""


def correlate(tables, neighbors):
    result = []
    uplinks = {n["interface_name"] for n in neighbors}
    addresses = [(".".join(index.split(".")[-4:]), mac) for index, mac in tables.get("arp_mac", {}).items()]
    import ipaddress

    for index, mac in tables.get("ndp_mac", {}).items():
        parts = [int(v) for v in index.split(".")]
        if len(parts) >= 3 and parts[1] in (1, 2) and parts[2] in (4, 16) and len(parts[3:]) == parts[2]:
            addresses.append((str(ipaddress.ip_address(bytes(parts[3:]))), mac))
    for address, mac in addresses:
        if not mac:
            continue
        suffix = ".".join(str(int(part, 16)) for part in mac.split(":"))
        candidates = []
        for key in ("fdb_port", "vlan_fdb_port"):
            for index, bridge in tables.get(key, {}).items():
                if index == suffix or index.endswith("." + suffix):
                    ifindex = tables.get("bridge_ifindex", {}).get(str(bridge))
                    if ifindex and ifindex not in candidates:
                        candidates.append(ifindex)
        result.append(
            {
                "ip": address,
                "mac": mac,
                "ifindex_candidates": candidates,
                "confidence": 0.8 if len(candidates) == 1 and not uplinks else 0.4,
                "source": "arp/ndp+fdb",
                "ambiguous": len(candidates) != 1 or bool(uplinks),
            }
        )
    return result
