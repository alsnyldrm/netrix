"""Follow fresh VLAN/MAC forwarding evidence from inventory backbone switches."""

from collections import defaultdict
from datetime import datetime


def backbone(device):
    kind = (device.device_type.name if device.device_type else device.kind).casefold()
    return kind in {"backbone", "backbone switch"} or "bb" in device.name.casefold().split("-")


def routed_ports(roots, static, vid, mac, cutoff):
    """Return terminal switch ports on a proven route, never transit ports."""
    snapshots = static["snapshots"]
    hops = defaultdict(set)
    peer_ports = defaultdict(set)
    transit = set()
    for record in static["records"]:
        local, port, remote, data, _, _ = record["link"]
        if record["down"]:
            continue
        stp_port = (data.get("spanning_tree") or {}).get("port")
        if stp_port:
            transit.add((local, stp_port))
        if not remote or remote == local:
            continue
        for key in record["blocks"]:
            transit.add(key)
            hops[key].add(remote)
        peer_ports[local, remote].add(port)
        remote_port = (data.get("lldp") or {}).get("port_id") or (data.get("cdp") or {}).get("port_id")
        if remote_port:
            transit.add((remote, remote_port))

    found = {}
    pending = [(root, None) for root in roots]
    visited = set()
    while pending:
        device, previous = pending.pop()
        if (device, previous) in visited or device not in snapshots:
            continue
        visited.add((device, previous))
        obs, p = snapshots[device]
        evidence = p["evidence"]
        if not evidence.get("neighbor_protocols_complete"):
            continue
        for port in p["fdb"].get((vid, mac), ()):
            observed = p["fdb_times"].get((vid, mac, port))
            if "_canonical_fdb_times" in evidence and not observed:
                continue
            at = observed or evidence.get("fdb_at") or obs.created_at.isoformat()
            if datetime.fromisoformat(at) < cutoff:
                continue
            key = device, port
            peers = hops[key]
            if peers:
                if len(peers) == 1 and previous not in peers:
                    pending.append((next(iter(peers)), device))
                continue
            if previous is None or key in transit or port in peer_ports[device, previous]:
                continue
            if any(n.get("interface_name") not in p["names"] for n in evidence.get("neighbors", [])):
                continue
            # Other learned MACs and endpoint neighbors on this port do not
            # contradict the target's exact VLAN/MAC forwarding entry.
            found[key] = obs, at
    return found
