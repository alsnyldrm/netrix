"""Follow fresh VLAN/MAC forwarding evidence from inventory backbone switches."""

from collections import defaultdict
from datetime import datetime


def backbone(device):
    kind = (device.device_type.name if device.device_type else device.kind).casefold()
    return kind in {"backbone", "backbone switch"} or "bb" in device.name.casefold().split("-")


def topology(static):
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

    return hops, peer_ports, transit


def fresh_ports(snapshot, vid, mac, cutoff):
    obs, projected = snapshot
    evidence = projected["evidence"]
    if not evidence.get("neighbor_protocols_complete"):
        return
    for port in projected["fdb"].get((vid, mac), ()):
        observed = projected["fdb_times"].get((vid, mac, port))
        if "_canonical_fdb_times" in evidence and not observed:
            continue
        at = observed or evidence.get("fdb_at") or obs.created_at.isoformat()
        if datetime.fromisoformat(at) >= cutoff:
            yield port, (obs, at)


def routed_ports(roots, static, vid, mac, cutoff):
    """Prefer a proven forwarding path, without treating uplinks as endpoint ports."""
    snapshots = static["snapshots"]
    hops, peer_ports, transit = topology(static)
    found = {}

    pending = [(root, None) for root in roots]
    visited = set()
    while pending:
        device, previous = pending.pop()
        if (device, previous) in visited or device not in snapshots:
            continue
        visited.add((device, previous))
        for port, proof in fresh_ports(snapshots[device], vid, mac, cutoff):
            key = device, port
            peers = hops[key]
            if peers:
                if len(peers) == 1 and previous not in peers:
                    pending.append((next(iter(peers)), device))
                continue
            if previous is None or key in transit or port in peer_ports[device, previous]:
                continue
            # Only mapped transit evidence can disqualify this exact port.
            # Unmapped neighbors on the switch do not invalidate the FDB match.
            found[key] = proof
    return found


def learned_peer(link, learned):
    from .connections import lldp_mac

    _, _, remote, data, _, _ = link
    if remote:
        return False
    lldp, cdp = data.get("lldp") or {}, data.get("cdp") or {}
    return lldp_mac(cdp.get("port_id")) in learned or (
        lldp.get("port_subtype") == 3 and lldp_mac(lldp.get("port_id")) in learned
    )


def terminal_ports(static, blocked, vid, mac, cutoff):
    _, _, transit = topology(static)
    peers_by_port = defaultdict(list)
    for record in static["records"]:
        if not record["down"]:
            for key in record["blocks"]:
                peers_by_port[key].append(record["link"])

    found = {}
    for device, snapshot in static["snapshots"].items():
        _, projected = snapshot
        if any(
            n.get("interface_name") not in projected["names"]
            for n in projected["evidence"].get("neighbors", [])
        ):
            # Unknown local ports could hide an uplink on this switch.
            continue
        for port, proof in fresh_ports(snapshot, vid, mac, cutoff):
            key = device, port
            if key in transit:
                continue
            if key in blocked:
                peers = peers_by_port[key]
                learned = projected["population"].get(port, set())
                # A phone or another local peer may share this port. Require
                # each advertised peer to have its own MAC learned on it.
                if not peers or not all(learned_peer(peer, learned) for peer in peers):
                    continue
            found[key] = proof
    return found
