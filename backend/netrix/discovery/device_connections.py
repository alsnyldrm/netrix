"""Read both ends of observed links; hierarchy is an inference, never routing proof."""

import heapq
import re

from sqlalchemy import select

from .. import models as m
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
        a, b = link.device_id, link.remote_device_id
        if a in devices and b in devices and a != b:
            adjacent[a].add(b)
            adjacent[b].add(a)
    anchors = {id: level for id, d in devices.items() if (level := anchor_level(d)) is not None}
    levels = dict(anchors)
    queue = [(level, id) for id, level in anchors.items()]
    heapq.heapify(queue)
    while queue:
        level, id = heapq.heappop(queue)
        if level != levels[id]:
            continue
        for peer in adjacent[id]:
            candidate = max(2, level + 1)
            if peer not in anchors and candidate < levels.get(peer, float("inf")):
                levels[peer] = candidate
                heapq.heappush(queue, (candidate, peer))
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
    for link in links:
        if device.id == link.device_id:
            peer_id = link.remote_device_id
            local_port, remote_port = link.interface_name, link.remote_port
            advertised_name = neighbor_label(link.remote_name)
        elif device.id == link.remote_device_id:
            peer_id = link.device_id
            local_port, remote_port = link.remote_port, link.interface_name
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
            entry["confidence"] = max(entry["confidence"], link.confidence)
            if observed and (not entry["last_seen_at"] or observed.isoformat() > entry["last_seen_at"]):
                entry["last_seen_at"] = observed.isoformat()
            continue
        connections[key] = {
            "id": link.id,
            "local_port": local_port or None,
            "remote_port": remote_port or None,
            "remote_device": (
                {"id": peer.id, "name": peer.name, "management_ip": peer.management_ip} if peer else None
            ),
            "remote_name": peer.name if peer else advertised_name,
            "direction": direction,
            "confidence": link.confidence,
            "sources": sorted(link.source.split("+")),
            "last_seen_at": observed.isoformat() if observed else None,
        }
    order = {"upstream": 0, "unknown": 1, "peer": 2, "downstream": 3}
    return {
        "items": sorted(
            connections.values(),
            key=lambda row: (order[row["direction"]], row["remote_name"], row["local_port"] or ""),
        )
    }
