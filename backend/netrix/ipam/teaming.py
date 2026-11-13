"""Display existing connections and known aggregate members on one IP row."""

from collections import defaultdict

from sqlalchemy import select

from .. import models as m


def display_members(db, items):
    from .pipeline import groups

    selected = [
        (item, item["connections"])
        for item in items
        if item.get("nic_teaming")
        and item.get("connections")
        and not item.get("connection_ambiguous")
        and item.get("connection_type") != "vcenter"
    ]
    pairs = {
        (connection["device_id"], connection.get("aggregate") or connection["port"])
        for _, connections in selected
        for connection in connections
    }
    if not pairs:
        return

    members = defaultdict(list)
    aggregates = {}
    for device, aggregate, port in db.execute(
        select(m.IPAMNetworkState.device_id, m.SourcePort.aggregate, m.SourcePort.name)
        .join(m.IPAMNetworkState, m.IPAMNetworkState.id == m.SourcePort.state_id)
        .where(
            m.SourcePort.aggregate != "",
            m.IPAMNetworkState.device_id.in_({device for device, _ in pairs}),
        )
        .order_by(m.SourcePort.name)
    ):
        if port and port != aggregate:
            members[device, aggregate].append(port)
            aggregates[device, port] = aggregate

    for item, connections in selected:
        expanded = {}
        for connection in connections:
            device, port = connection["device_id"], connection["port"]
            aggregate = connection.get("aggregate") or aggregates.get((device, port), port)
            related = members.get((device, aggregate), ())
            ports = related or (port,)
            for member in ports:
                value = {
                    **connection,
                    "port": member,
                    "aggregate": aggregate if related else connection.get("aggregate"),
                }
                if member != port:
                    value.pop("remote_port", None)
                    value.pop("nic", None)
                    value.pop("mac_address", None)
                expanded.setdefault((device, member), value)
        connections = list(expanded.values())
        grouped = groups(connections)
        item.update(
            connections=connections,
            connection_groups=grouped,
            connected_device=" / ".join(group["device_name"] for group in grouped),
            connected_port=" / ".join(group["port_label"] for group in grouped),
        )
