"""Interpret LLDP identifiers by subtype; correlate CDP only with matching chassis evidence."""

from .neighbor_labels import neighbor_label


def integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def octets(value):
    if hasattr(value, "asOctets"):
        return value.asOctets()
    return value if isinstance(value, bytes) else None


def identifier(value, is_mac=False):
    raw = octets(value)
    if is_mac and raw is not None:
        return ":".join(f"{byte:02x}" for byte in raw) if len(raw) == 6 else "0x" + raw.hex()
    return neighbor_label(value)


def local_port(tables, index):
    port_id = neighbor_label(tables.get("lldp_local_id", {}).get(index))
    description = neighbor_label(tables.get("lldp_local_desc", {}).get(index))
    subtype = integer(tables.get("lldp_local_type", {}).get(index))
    interfaces = {i: neighbor_label(v) for i, v in tables.get("if_name", {}).items()}
    descriptions = {i: neighbor_label(v) for i, v in tables.get("if_descr", {}).items()}
    # LLDP localPortNum is NOT generally an IF-MIB ifIndex. Resolve the
    # advertised ID/description, never assume equal numeric indices.
    matches = set()
    for ifindex, name in interfaces.items():
        if (subtype == 5 and port_id == name) or (
            description and description in (name, descriptions.get(ifindex))
        ):
            matches.add(name)
        if subtype == 1 and port_id == neighbor_label(tables.get("if_alias", {}).get(ifindex)):
            matches.add(name)
        if subtype == 3 and identifier(tables.get("lldp_local_id", {}).get(index), True) == identifier(
            tables.get("if_mac", {}).get(ifindex), True
        ):
            matches.add(name)
    return next(iter(matches)) if len(matches) == 1 else port_id or f"LLDP-port-{index}"


def parse_neighbors(tables):
    neighbors = []
    indices = dict.fromkeys(
        i for key in ("lldp_chassis", "lldp_name", "lldp_port") for i in tables.get(key, {})
    )
    for index in indices:
        parts = index.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        local_index = parts[1]
        chassis_type = integer(tables.get("lldp_chassis_type", {}).get(index))
        port_type = integer(tables.get("lldp_port_type", {}).get(index))
        chassis = identifier(tables.get("lldp_chassis", {}).get(index), chassis_type == 4)
        name = neighbor_label(tables.get("lldp_name", {}).get(index))
        port = identifier(tables.get("lldp_port", {}).get(index), port_type == 3)
        lldp = {
            "index": index,
            "local_port_number": local_index,
            "local_port_id": neighbor_label(tables.get("lldp_local_id", {}).get(local_index)),
            "chassis_subtype": chassis_type,
            "chassis_id": chassis,
            "system_name": name,
            "port_subtype": port_type,
            "port_id": port,
            "port_description": neighbor_label(tables.get("lldp_port_desc", {}).get(index)),
        }
        neighbors.append(
            {
                "interface_name": local_port(tables, local_index)[:120],
                "remote_name": (name or chassis or "Bilinmeyen komşu")[:190],
                "remote_port": port[:120],
                "source": "lldp",
                "evidence": {"lldp": lldp},
            }
        )
    for index, device_id in tables.get("cdp_name", {}).items():
        parts = index.split(".")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            continue
        ifindex = parts[0]
        local = neighbor_label(
            tables.get("if_name", {}).get(ifindex)
            or tables.get("if_descr", {}).get(ifindex)
            or f"ifIndex-{ifindex}"
        )
        name = neighbor_label(tables.get("cdp_sysname", {}).get(index))
        remote_id = neighbor_label(device_id)
        port = neighbor_label(tables.get("cdp_port", {}).get(index))
        raw_id = octets(device_id)
        mac_id = identifier(device_id, True) if raw_id is not None and len(raw_id) == 6 else None
        cdp = {
            "index": index,
            "device_id": remote_id,
            "device_id_hex": raw_id.hex() if raw_id is not None else None,
            "system_name": name,
            "port_id": port,
        }
        matches = [
            n
            for n in neighbors
            if n["interface_name"] == local
            and n["source"] == "lldp"
            and (
                mac_id
                and n["evidence"]["lldp"]["chassis_subtype"] == 4
                and n["evidence"]["lldp"]["chassis_id"] == mac_id
            )
        ]
        # A shared port or similar name alone is never enough to join records.
        if len(matches) == 1:
            match = matches[0]
            lldp_name = match["evidence"]["lldp"]["system_name"]
            if not name or not lldp_name or name == lldp_name:
                cdp["device_id"] = mac_id
                match["source"] = "lldp+cdp"
                match["evidence"]["cdp"] = cdp
                if not lldp_name and name:
                    match["remote_name"] = name[:190]
                continue
        neighbors.append(
            {
                "interface_name": local[:120],
                "remote_name": (name or remote_id)[:190],
                "remote_port": port[:120],
                "source": "cdp",
                "evidence": {"cdp": cdp},
            }
        )
    return neighbors
