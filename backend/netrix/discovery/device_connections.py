"""Read both ends of observed links; hierarchy is an inference, never routing proof."""

import heapq
import re

from sqlalchemy import select

from .. import models as m
from .link_edits import confidence, name_label, port_label
from .link_edits import peer_id as effective_peer_id
from .neighbor_labels import neighbor_label


def anchor_level(device):
    kind = (device.device_type.name if device.device_type else device.kind).casefold()
    if device.kind == "firewall":
        return 0
    if kind in {"backbone", "controller", "wireless controller"} or re.search(
        r"(?:^|-)BB(?:-|$)", device.name, re.I
    ):
        return 1
    return None


def hierarchy(devices, links):
    adjacent = {id: set() for id in devices}
    for link in links:
        a, b = link.device_id, effective_peer_id(link)
        if a in devices and b in devices and a != b:
            adjacent[a].add(b)
            adjacent[b].add(a)
    # Prefer firewall roots for their whole connected component. A second
    # Backbone behind a core must not be pinned to the same level as that core.
    anchors = {id: 0 for id, d in devices.items() if anchor_level(d) == 0}
    levels = {}

    def visit(seeds):
        queue = list(seeds)
        heapq.heapify(queue)
        while queue:
            level, id = heapq.heappop(queue)
            if id in levels:
                continue
            levels[id] = level
            for peer in adjacent[id]:
                if peer not in levels:
                    heapq.heappush(queue, (level + 1, peer))

    visit([(level, id) for id, level in anchors.items()])
    visit([(1, id) for id, d in devices.items() if id not in levels and anchor_level(d) == 1])
    # A disconnected component without a known root has no inferred direction.
    return levels


def device_connections(db, device):
    devices = {
        d.id: d
        for d in db.scalars(
            select(m.Device).where(m.Device.vrf_id == device.vrf_id, m.Device.archived.is_(False))
        )
    }
    if device.id not in devices:
        return {"items": []}
    links = list(
        db.scalars(
            select(m.Link)
            .join(m.Device, m.Device.id == m.Link.device_id)
            .where(
                m.Device.vrf_id == device.vrf_id, m.Device.archived.is_(False), m.Link.is_current.is_(True)
            )
        )
    )
    levels = hierarchy(devices, links)
    connections = {}
    aggregates = {}
    roots = {}
    for row in sorted(links, key=lambda l: l.last_seen_at or l.updated_at):
        evidence = row.evidence or {}
        if "local_aggregate" in evidence:
            aggregates[(row.device_id, row.interface_name)] = evidence["local_aggregate"]
        if evidence.get("spanning_tree"):
            roots[row.device_id] = evidence["spanning_tree"]

    for link in links:
        if device.id == link.device_id:
            peer_id = effective_peer_id(link)
            local_port, remote_port = (
                link.interface_name,
                port_label(link),
            )
            advertised_name = name_label(link)
        elif device.id == effective_peer_id(link):
            peer_id = link.device_id
            local_port, remote_port = (
                port_label(link),
                link.interface_name,
            )
            advertised_name = devices[peer_id].name
        else:
            continue
        if peer_id == device.id or (peer_id and peer_id not in devices):
            continue
        peer = devices.get(peer_id)
        direction = "unknown"
        if device.id in levels and peer_id in levels:
            delta = levels[peer_id] - levels[device.id]
            direction = "upstream" if delta < 0 else "downstream" if delta > 0 else "peer"
        local_port, remote_port = neighbor_label(local_port), neighbor_label(remote_port)
        local_aggregate = aggregates.get((device.id, local_port))
        remote_aggregate = aggregates.get((peer_id, remote_port))
        root = roots.get(device.id)
        basis = "topology"
        if root and root.get("port"):
            basis = "stp"
            direction = (
                "upstream"
                if root.get("port") and root["port"] in (local_port, (local_aggregate or {}).get("name"))
                else "unknown"
            )

        # Merge only identical endpoints; parallel links and unresolved ports stay distinct.
        key = (
            peer_id or advertised_name,
            local_port,
            remote_port,
            "" if local_port and remote_port else link.id,
        )
        observed = link.last_seen_at
        entry = connections.get(key)
        if entry:
            entry["sources"] = sorted(set(entry["sources"]) | set(link.source.split("+")))
            entry["confidence"] = max(entry["confidence"], confidence(link))
            if observed and (not entry["last_seen_at"] or observed.isoformat() > entry["last_seen_at"]):
                entry["last_seen_at"] = observed.isoformat()
            continue
        connections[key] = {
            "id": link.id,
            "local_port": local_port or None,
            "local_aggregate": local_aggregate,
            "remote_aggregate": remote_aggregate,
            "direction_basis": basis,
            "remote_port": remote_port or None,
            "remote_device": (
                {"id": peer.id, "name": peer.name, "management_ip": peer.management_ip} if peer else None
            ),
            "remote_name": peer.name if peer else advertised_name,
            "direction": direction,
            "confidence": confidence(link),
            "sources": sorted(link.source.split("+")),
            "last_seen_at": observed.isoformat() if observed else None,
        }
    grouped = {}
    for row in connections.values():
        aggregate = row["local_aggregate"]
        key = (
            (
                row["remote_device"]["id"] if row["remote_device"] else row["remote_name"],
                aggregate["name"],
                row["direction"],
            )
            if aggregate
            else (row["id"],)
        )
        member = {"local_port": row["local_port"], "remote_port": row["remote_port"]}
        if key in grouped:
            existing = grouped[key]
            existing["members"].append(member)
            existing["sources"] = sorted(set(existing["sources"]) | set(row["sources"]))
            existing["confidence"] = min(existing["confidence"], row["confidence"])
            if existing["remote_aggregate"] != row["remote_aggregate"]:
                existing["remote_aggregate"] = None
        else:
            grouped[key] = {**row, "members": [member] if aggregate else []}
    order = {"upstream": 0, "unknown": 1, "peer": 2, "downstream": 3}
    return {
        "items": sorted(
            grouped.values(),
            key=lambda row: (order[row["direction"]], row["remote_name"], row["local_port"] or ""),
        )
    }
