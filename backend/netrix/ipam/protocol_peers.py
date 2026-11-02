"""Physical host ownership from authenticated, agreeing LLDP and CDP detail."""

from .connections import ip


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
