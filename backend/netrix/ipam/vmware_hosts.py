"""Authenticated ESXi host/IP/NIC ownership and read-only physical link hints."""

import ipaddress
from datetime import timedelta

from ..core import now


def text(value):
    return str(value or "")[:190]


def hints(rows):
    """Keep scalar, documented LLDP/CDP fields; never serialize SDK objects."""
    result = {}
    for row in rows:
        endpoints = []
        cdp = getattr(row, "connectedSwitchPort", None)
        if cdp and getattr(cdp, "portId", None):
            endpoints.append(
                dict(
                    protocol="cdp",
                    addresses=[
                        text(v) for v in (getattr(cdp, "mgmtAddr", ""), getattr(cdp, "address", "")) if v
                    ],
                    port_id=text(cdp.portId),
                    port_description="",
                    chassis_id=text(getattr(cdp, "devId", "")),
                )
            )
        lldp = getattr(row, "lldpInfo", None)
        if lldp and getattr(lldp, "timeToLive", 0) > 0:
            params = list(getattr(lldp, "parameter", None) or [])
            endpoints.append(
                dict(
                    protocol="lldp",
                    addresses=[text(p.value) for p in params if p.key == "Management Address"],
                    port_id=text(lldp.portId),
                    port_description=next((text(p.value) for p in params if p.key == "Port Description"), ""),
                    chassis_id=text(lldp.chassisId),
                )
            )
        result[text(row.device)] = endpoints
    return result


def records(host_id, values, network_hints=None):
    from .service import normalized_mac

    if values.get("runtime.connectionState", "connected") != "connected":
        return []
    pnics = [
        {
            "device": text(p.device),
            "mac_address": normalized_mac(p.mac),
            "link_up": bool(p.linkSpeed),
            "hints": (network_hints or {}).get(p.device, []),
        }
        for p in values.get("config.network.pnic") or []
    ]
    rows = []
    for vnic in values.get("config.network.vnic") or []:
        spec = vnic.spec
        uplinks = uplink_devices(vnic, values)
        config = getattr(spec, "ip", None)
        addresses = [getattr(config, "ipAddress", "")]
        addresses += [
            a.ipAddress for a in getattr(getattr(config, "ipV6Config", None), "ipV6Address", None) or []
        ]
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
                if address.is_unspecified or address.is_link_local or address.is_loopback:
                    continue
            except ValueError:
                continue
            rows.append(
                {
                    "record_type": "host",
                    "address": str(address),
                    "host_address": str(address),
                    "hostname": text(values.get("name")),
                    "host_id": host_id,
                    "host_uuid": text(values.get("hardware.systemInfo.uuid")),
                    "vmkernel_device": text(vnic.device),
                    "mac_address": normalized_mac(getattr(spec, "mac", "")),
                    "uplink_nics": sorted(uplinks),
                    "physical_nics": [{**n, "carries_ip": n["device"] in uplinks} for n in pnics],
                    "operating_system": text(values.get("config.product.fullName")),
                    "power_state": text(values.get("runtime.powerState")),
                }
            )
    return rows


def uplink_devices(vnic, values):
    """VMkernel -> its own standard/distributed switch -> physical NICs."""
    spec = vnic.spec
    pinned = getattr(spec, "pinnedPnicDevice", None)
    if pinned:
        return {pinned}
    port = getattr(spec, "distributedVirtualPort", None)
    switch_uuid = getattr(port, "switchUuid", None)
    keys = set()
    if switch_uuid:
        for switch in values.get("config.network.proxySwitch") or []:
            if switch.dvsUuid == switch_uuid:
                keys.update(switch.pnic or [])
    else:
        group = getattr(vnic, "portgroup", "")
        names = {
            pg.spec.vswitchName
            for pg in values.get("config.network.portgroup") or []
            if pg.spec.name == group
        }
        for switch in values.get("config.network.vswitch") or []:
            if switch.name in names:
                keys.update(switch.pnic or [])
    return {
        p.device
        for p in values.get("config.network.pnic") or []
        if getattr(p, "key", None) in keys or p.device in keys
    }


def active_nics(host):
    return [n for n in host.get("physical_nics", []) if n.get("link_up")]


def select_host(observations, address, gateway_mac, *, at=None, lifetime=None):
    """A host IP and its VMkernel MAC must agree; unrelated NIC MACs are not conflicts."""
    from .service import normalized_mac

    cutoff = (at or now()) - (lifetime or timedelta(hours=24))
    candidates = [
        o
        for o in observations
        if o.source == "vcenter"
        and o.observed_at >= cutoff
        and o.data.get("present", True)
        and o.data.get("record_type") == "host"
        and o.data.get("host_address") == address
    ]
    owners = {(o.data.get("integration_id", o.source_key), o.data.get("host_id")) for o in candidates}
    if len(owners) != 1 or not next(iter(owners))[1]:
        return None
    macs = {normalized_mac(o.data.get("mac_address")) for o in candidates}
    if len(macs) != 1 or not next(iter(macs)) or (gateway_mac and macs != {gateway_mac}):
        return None
    observation = max(candidates, key=lambda o: o.observed_at)
    data = observation.data
    return {
        **data,
        "identity": "vcenter-host:" + ":".join(next(iter(owners))),
        "observed_at": observation.observed_at.isoformat(),
        "evidence_id": observation.id,
    }


def nic_for_neighbor(host, data):
    """Typed NIC MAC or typed chassis + exact NIC name, never a display label."""
    from .service import normalized_hostname, normalized_mac

    if not host:
        return None
    active = [n for n in active_nics(host) if normalized_mac(n.get("mac_address"))]
    ll = data.get("lldp") or {}
    port_mac = normalized_mac(ll.get("port_id")) if ll.get("port_subtype") == 3 else ""
    chassis_mac = normalized_mac(ll.get("chassis_id")) if ll.get("chassis_subtype") == 4 else ""
    # Port MAC identifies this NIC; a chassis MAC can identify the host's
    # first card while another port advertises its own different card.
    matches = [n for n in active if port_mac and n["mac_address"] == port_mac]
    if len(matches) == 1:
        return matches[0]
    chassis = normalized_hostname(ll.get("chassis_id"))
    if (
        ll.get("chassis_subtype") == 7
        and chassis
        and chassis in {normalized_hostname(host.get("host_uuid")), normalized_hostname(host.get("hostname"))}
    ):
        return next((n for n in active if n["device"] == ll.get("port_id")), None)
    matches = [n for n in active if chassis_mac and n["mac_address"] == chassis_mac]
    if len(matches) == 1 and not port_mac:
        return matches[0]
    return None
