"""Physical host ownership from authenticated, agreeing LLDP and CDP detail."""

import ipaddress
import re

from .connections import ip, lldp_mac


def peer(data, address):
    from .service import normalized_mac

    lldp, cdp = data.get("lldp") or {}, data.get("cdp") or {}
    if lldp.get("transport") != "ssh_detail" or cdp.get("transport") != "ssh_detail":
        return None
    if lldp.get("chassis_subtype") != 4 or lldp.get("port_subtype") != 3:
        return None
    chassis, nic = normalized_mac(lldp.get("chassis_id")), normalized_mac(lldp.get("port_id"))
    if (
        not chassis
        or not nic
        or normalized_mac(cdp.get("device_id")) != chassis
        or ip(cdp.get("management_address")) != address
    ):
        return None
    if int(chassis[:2], 16) & 1 or int(nic[:2], 16) & 1:
        return None
    return {"identity": "ssh-peer:" + chassis, "nic": cdp.get("port_id") or nic, "mac_address": nic}



def hostname_evidence(data, address, macs):
    """Use a protocol's system name only when that same observation identifies the endpoint."""
    for source in ("lldp", "cdp"):
        fact = data.get(source) or {}
        name = (fact.get("system_name") or "").strip().rstrip(".")
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,188}[A-Za-z0-9])?", name):
            continue
        if ip(name) or lldp_mac(name) or not any(c.isalpha() for c in name):
            continue
        advertised_ip = ip(fact.get("management_address"))
        if source == "lldp":
            chassis = fact.get("chassis_id") or ""
            if not advertised_ip and fact.get("chassis_subtype") == 5:
                advertised_ip = ip(chassis)
                if not advertised_ip and re.fullmatch(r"0x01[0-9a-fA-F]{8}", chassis):
                    advertised_ip = str(ipaddress.IPv4Address(bytes.fromhex(chassis[4:])))
            identifiers = (
                fact.get("chassis_id") if fact.get("chassis_subtype") == 4 else None,
                fact.get("port_id") if fact.get("port_subtype") == 3 else None,
            )
        else:
            identifiers = (fact.get("device_id"), fact.get("port_id"))
        advertised_macs = {mac for value in identifiers if (mac := lldp_mac(value))}
        if advertised_ip and advertised_ip != address:
            continue
        if macs and advertised_macs and not macs & advertised_macs:
            continue
        if advertised_ip == address or macs & advertised_macs:
            yield source, name
