"""Resolve VMware physical hints using existing inventory IPs and current ports."""

from .connections import integer, ip


def hint_candidates(evidence, host, row, snapshots):
    from .vmware_hosts import active_nics

    result = []
    for nic in active_nics(host):
        for hint in nic.get("hints", []):
            addresses = {a for value in hint.get("addresses", []) if (a := ip(value))}
            switches = [
                d
                for d in evidence.devices.values()
                if d.vrf_id == row.vrf_id and d.management_ip in addresses
            ]
            if len(switches) != 1:
                continue
            device = switches[0]
            snapshot = snapshots.get(device.id)
            if not snapshot or snapshot[1]["evidence"].get("failed"):
                continue
            obs, p = snapshot
            # LLDP portId can be a numeric local identifier. Resolve it with
            # ifIndex/name evidence, never print the number as a physical label.
            names = {i.get("name"): i for i in p["interfaces"].values()}
            candidates = {v for v in (hint.get("port_id"), hint.get("port_description")) if v in names}
            indexed = p["interfaces"].get(integer(hint.get("port_id")))
            if indexed and indexed.get("name"):
                candidates.add(indexed["name"])
            if len(candidates) != 1:
                continue
            port = next(iter(candidates))
            if names[port].get("oper_status") != "up":
                continue
            # A fresh independent VMware observation does not restore or use
            # any excluded directory record. The inventory remains unchanged.
            # An explicit infrastructure peer on that port contradicts a host.
            raw = [
                *evidence.raw_neighbors.get(device.id, []),
                *evidence.excluded_raw_neighbors.get(device.id, []),
            ]
            if any(
                n.get("interface_name") == port
                and any(
                    ip((n.get("evidence", {}).get(proto) or {}).get("management_address")) == d.management_ip
                    for proto in ("lldp", "cdp")
                    for d in evidence.devices.values()
                    if d.id != device.id
                )
                for n in raw
            ):
                continue
            result.append(
                {
                    "device_id": device.id,
                    "device_name": device.name,
                    "port": port,
                    "aggregate": None,
                    "source": "vcenter_host+" + hint["protocol"],
                    "observed_at": host["observed_at"],
                    "evidence_id": host["evidence_id"],
                    "endpoint_identity": host["identity"],
                    "nic": nic["device"],
                    "mac_address": nic["mac_address"],
                    "confidence": 0.98,
                }
            )
    return result
