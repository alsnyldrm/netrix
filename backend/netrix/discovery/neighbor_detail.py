"""Bounded AOS-S detail observations; never infer port names from numeric identifiers."""

import ipaddress
import re

from .neighbor_labels import neighbor_label

AOS_SWITCH = {"aruba_5400", "aruba_2900"}
PORT = re.compile(r"[A-Za-z0-9][A-Za-z0-9/.-]{0,39}\Z")


def mac(value):
    value = re.sub(r"[ :.-]", "", value or "").lower()
    return ":".join(value[i : i + 2] for i in range(0, 12, 2)) if re.fullmatch(r"[0-9a-f]{12}", value) else ""


def ip(value):
    try:
        address = ipaddress.ip_address(value)
        return str(address) if not address.is_unspecified else ""
    except ValueError:
        return ""


def remote_port(evidence, fallback=""):
    """CDP Device Port is explicit. LLDP local IDs require the advertised description."""
    cdp, lldp = evidence.get("cdp", {}), evidence.get("lldp", {})
    if cdp.get("port_id"):
        return neighbor_label(cdp["port_id"])
    if lldp:
        if lldp.get("port_subtype") == 7:
            return neighbor_label(lldp.get("port_description"))
        return neighbor_label(lldp.get("port_id"))
    return neighbor_label(fallback)


def chassis(row):
    e = row.get("evidence", {})
    return mac(e.get("lldp", {}).get("chassis_id")) or mac(e.get("cdp", {}).get("device_id"))


def addresses(row):
    e = row.get("evidence", {})
    return {v for p in ("lldp", "cdp") if (v := ip(e.get(p, {}).get("management_address", "")))}


def same_neighbor(a, b):
    if a["interface_name"] != b["interface_name"]:
        return False
    ac, bc = chassis(a), chassis(b)
    if ac and bc:
        return ac == bc
    aa, ba = addresses(a), addresses(b)
    return bool(aa and ba and aa == ba)


def merge_neighbors(base, details):
    rows = [dict(n, evidence=dict(n.get("evidence", {}))) for n in base]
    for detail in details:
        matches = [n for n in rows if same_neighbor(n, detail)]
        if len(matches) == 1:
            row = matches[0]
            row["evidence"] = {**row["evidence"], **detail["evidence"]}
            sources = set(row["source"].split("+")) | set(detail["source"].split("+"))
            # Keep the API/filter's canonical LLDP + CDP value.
            row["source"] = "+".join(sorted(sources, key=lambda protocol: (protocol != "lldp", protocol)))
            name = row["evidence"].get("lldp", {}).get("system_name")
            row["remote_name"] = name or row["remote_name"]
            row["remote_port"] = remote_port(row["evidence"])
        else:
            rows.append(detail)
    return rows


def parse_detail(output, protocol):
    start = "Local Port" if protocol == "lldp" else "Port"
    blocks = re.split(r"(?m)^\s*" + start + r"\s*:\s*", output)[1:]
    rows = []
    for block in blocks:
        lines = block.splitlines()
        local = lines[0].strip()
        if not PORT.fullmatch(local):
            continue
        fields = dict(
            re.findall(r"(?m)^[ \t]*([A-Za-z][A-Za-z ]*?)[ \t]*:[ \t]*([^\r\n]*)", "\n".join(lines[1:]))
        )
        fields = {k.strip(): v.strip() for k, v in fields.items()}
        if protocol == "lldp":
            evidence = {
                "chassis_id": mac(fields.get("ChassisId")) or fields.get("ChassisId", ""),
                "chassis_subtype": 4 if fields.get("ChassisType") == "mac-address" else None,
                "system_name": fields.get("SysName", ""),
                "port_subtype": {"local": 7, "interface-name": 5, "mac-address": 3}.get(
                    fields.get("PortType")
                ),
                "port_id": fields.get("PortId", ""),
                "port_description": fields.get("PortDescr", ""),
                "management_address": ip(fields.get("Address", "")),
            }
            name = evidence["system_name"] or evidence["chassis_id"]
        else:
            evidence = {
                "device_id": mac(fields.get("Device ID")) or fields.get("Device ID", ""),
                "port_id": fields.get("Device Port", ""),
                "management_address": ip(fields.get("Address", "")),
            }
            name = evidence["device_id"]
        if not name:
            continue
        evidence["transport"] = "ssh_detail"
        e = {protocol: evidence}
        rows.append(
            {
                "interface_name": local,
                "remote_name": name[:190],
                "remote_port": remote_port(e)[:120],
                "source": protocol,
                "evidence": e,
            }
        )
    return rows


def parse_trunks(output):
    # Interface descriptions may themselves contain '|'; use the final group column.
    result = {}
    for line in output.splitlines():
        match = re.match(r"\s*(\S+)\s+\|.*\|\s*((?:Trk|Dyn)\d+)\s+(LACP|Trunk)\s*$", line, re.I)
        if match and PORT.fullmatch(match[1]):
            result[match[1]] = {"name": match[2], "type": match[3], "source": "show trunks"}
    return result


def parse_root(output):
    match = re.search(r"(?m)^\s*(?:CST )?Root Port\s*:\s*([^\r\n]+)", output)
    if not match:
        return None
    value = match[1].strip()
    if value.lower() == "this switch is root":
        return {"port": None, "is_root": True, "source": "show spanning-tree"}
    if PORT.fullmatch(value):
        return {"port": value, "is_root": False, "source": "show spanning-tree"}
    return None


def enrich_neighbors(collected, detail):
    collected["neighbors"] = merge_neighbors(collected.get("neighbors", []), detail.get("neighbors", []))
    collected["neighbor_detail"] = {k: v for k, v in detail.items() if k != "neighbors"}
    collected["neighbor_protocols_complete"] = sorted(
        set(collected.get("neighbor_protocols_complete", []))
        | set(detail.get("neighbor_protocols_complete", []))
    )
    for row in collected["neighbors"]:
        evidence = row["evidence"] = dict(row.get("evidence", {}))
        if "trunks" in detail:
            evidence["local_aggregate"] = detail["trunks"].get(row["interface_name"])
        if "spanning_tree" in detail:
            evidence["spanning_tree"] = detail["spanning_tree"]
    return collected
