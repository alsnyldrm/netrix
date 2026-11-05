"""Canonical switch/gateway facts. Protocol dictionaries exist only during processing."""

import ipaddress

from sqlalchemy import select

from .. import models as m
from .records import find, gateway, source_write


def state_for(db, device_id, address):
    if device_id:
        db.scalar(select(m.Device.id).where(m.Device.id == device_id).with_for_update())
    actual = db.get(m.Device, device_id) if device_id else None
    row = (
        find(db, m.IPAMNetworkState, device_id=actual.id)
        if actual
        else find(db, m.IPAMNetworkState, device_id=None, address=address)
    )
    if not row.address or (actual and address == actual.management_ip):
        row.address = address
    return row


def port_for(state, name, index=None):
    named = [p for p in state.ports if name and p.name == name]
    row = (
        named[0]
        if len(named) == 1
        else next((p for p in state.ports if index is not None and p.if_index == index), None)
    )
    if row is None:
        row = m.SourcePort(id=m.uid(), name=name or "", if_index=index)
        state.ports.append(row)
    elif index is not None:
        row.if_index = index
        if name:
            row.name = name
    return row


def prefixes(tables):
    result = set()
    for key, index in tables.get("ip_addr_ifindex", {}).items():
        try:
            address = tables.get("ip_addr_address", {}).get(key, key)
            subnet = ipaddress.ip_network(f"{address}/{tables['ip_addr_mask'][key]}", strict=False)
            result.add((int(index), str(subnet.network_address), subnet.prefixlen))
        except (KeyError, ValueError, TypeError):
            pass
    for key, index in tables.get("ip_address_ifindex", {}).items():
        pointer = str(tables.get("ip_address_prefix", {}).get(key, "")).lstrip(".")
        base = "1.3.6.1.2.1.4.32.1.5."
        if not pointer.startswith(base):
            continue
        try:
            p = [int(v) for v in pointer[len(base) :].split(".")]
            length = {1: 4, 2: 16}.get(p[1], 0)
            octets = (
                p[3:-1]
                if len(p) == length + 4 and p[2] == length
                else p[2:-1]
                if len(p) == length + 3
                else []
            )
            if length and len(octets) == length and p[0] == int(index):
                subnet = ipaddress.ip_network((ipaddress.ip_address(bytes(octets)), p[-1]), strict=False)
                result.add((int(index), str(subnet.network_address), subnet.prefixlen))
        except (ValueError, IndexError, TypeError):
            pass
    for item in tables.get("_prefixes", []):
        result.add((item["if_index"], item["address"], item["prefix_length"]))
    return result


@source_write
def write(db, state, data, at):
    from ..discovery.links import legacy_match
    from ..discovery.neighbor_detail import same_neighbor
    from .neighbors import write as write_neighbor

    if not state.id:
        state.id = m.uid()
    device = db.get(m.Device, state.device_id) if state.device_id else None
    tables = data.get("tables") or {}
    state.observed_at = max(state.observed_at, at) if state.observed_at else at
    if not state.attempted_at or state.attempted_at <= at:
        state.attempted_at = at
        state.healthy = not data.get("failed", False)
    if data.get("read_context"):
        context = data["read_context"]
        if len(context) == 8:
            context = [
                context[0],
                context[1],
                context[2],
                context[5],
                context[6],
                context[4],
                device.config_port if device else 22,
                device.ssh_trust_host_key if device else False,
                None,
                None,
            ]
        state.read_context = context
    elif device and not state.read_context and device.snmp_credential_id:
        from ..ipam.network import detail_profile, read_context

        profile = db.get(m.Credential, device.snmp_credential_id)
        if profile:
            state.read_context = read_context(device, profile, detail_profile(db, device))
    unsupported = set(data.get("unsupported") or [])
    known = {r.name: r for r in state.unsupported}
    previous_success = {name: r.successful_at for name, r in known.items()}
    outcomes = data.get("table_reads") or {
        key: dict(status="error" if key in unsupported else "complete", row_count=len(value))
        for key, value in tables.items()
        if not key.startswith("_")
    }
    for key in unsupported:
        outcomes.setdefault(key, dict(status="error", row_count=0))
    # Unqueried tables are untouched. Late completions cannot replace newer data.
    stale_tables = {
        key for key in tables if key in known and known[key].attempted_at and known[key].attempted_at > at
    }
    for key, outcome in outcomes.items():
        old = known.get(key)
        if old and old.attempted_at and old.attempted_at > at:
            continue
        entry = old or m.UnsupportedTable(name=key)
        if old is None:
            state.unsupported.append(entry)
        entry.status = outcome.get("status", "error")
        if key in unsupported and entry.status == "complete":
            entry.status = "error"
        entry.row_count = outcome.get("row_count", 0)
        entry.error_code = outcome.get("error_code", "")[:80]
        entry.attempted_at = at
        if entry.status == "complete":
            entry.successful_at = at
        known[key] = entry
    tables = {k: v for k, v in tables.items() if k not in stale_tables}
    if data.get("failed"):
        tables = {}

    def complete(*keys):
        return all(
            k in tables
            and k not in unsupported
            and outcomes.get(k, {}).get("status", "complete") == "complete"
            for k in keys
        )

    required = {"vlan_fdb_port", "vlan_fdb_status", "bridge_ifindex"}
    fresh_fdb = not state.fdb_at or at >= state.fdb_at
    fdb_complete = fresh_fdb and complete(*required)
    if "neighbor_detail_failed" in data:
        state.neighbor_detail_failed = str(data["neighbor_detail_failed"] or "")[:80]
    elif "neighbor_detail" in data or (
        "read_context" in data and len(data["read_context"]) == 10 and data["read_context"][8] is None
    ):
        state.neighbor_detail_failed = ""
    identity = data.get("identity") or {}
    if (not state.identity_at or at >= state.identity_at) and any(
        k in data
        for k in ("identity", "hostname", "sys_description", "sys_object_id", "uptime", "ip_forwarding")
    ):
        state.identity_at = at
        info = state.identity or m.DeviceSourceIdentity()
        state.identity = info
        for name in ("hostname", "sys_description", "sys_object_id", "uptime", "ip_forwarding"):
            if name in data:
                setattr(info, name, str(data[name] or ""))
        for name in ("vendor", "model", "serial", "kind", "software_version", "location", "system_name"):
            if name in identity:
                setattr(info, name, str(identity[name] or "")[:190])
            if name in (data.get("field_sources") or {}):
                setattr(info, name + "_source", data["field_sources"][name])
    interfaces = list(data.get("interfaces") or [])
    # Some older inventory snapshots omitted the interface array but retained IF-MIB.
    names = tables.get("if_name") or tables.get("if_descr") or {}
    have = {str(p.get("if_index")) for p in interfaces}
    for index, name in names.items():
        if str(index) not in have:
            interfaces.append(
                dict(
                    if_index=int(index),
                    name=name,
                    oper_status="up" if tables.get("if_status", {}).get(str(index)) == "1" else "down",
                )
            )
    if state.interfaces_at and at < state.interfaces_at:
        interfaces = []
    elif interfaces:
        state.interfaces_at = at
    # SNMP ifIndex values can swap after a restart. Release changed persistent
    # indexes before the final ORM updates to satisfy the immediate UNIQUE key.
    reassigned = [
        p
        for p in state.ports
        if p.id
        and any(
            item.get("name") == p.name
            and item.get("if_index") is not None
            and int(item["if_index"]) != p.if_index
            for item in interfaces
        )
    ]
    if reassigned:
        from sqlalchemy import inspect, update
        from sqlalchemy.orm.attributes import set_committed_value

        existing = [p for p in reassigned if inspect(p).persistent]
        if existing:
            db.execute(
                update(m.SourcePort)
                .where(m.SourcePort.id.in_([p.id for p in existing]))
                .values(if_index=None)
                .execution_options(synchronize_session=False)
            )
            for port in existing:
                set_committed_value(port, "if_index", None)
    for item in interfaces:
        if item.get("if_index") is None:
            continue
        port_name = item.get("name") or ""
        if "if_name" in unsupported:
            previous_port = next((p for p in state.ports if p.if_index == int(item["if_index"])), None)
            if previous_port:
                port_name = previous_port.name
        port = port_for(state, port_name, int(item["if_index"]))
        field_tables = {
            "description": "if_descr",
            "mac_address": "if_mac",
            "oper_status": "if_status",
            "speed_bps": "if_speed",
        }
        for name in ("description", "mac_address", "admin_status", "oper_status", "speed_bps"):
            if item.get(name) is not None and field_tables.get(name) not in unsupported:
                setattr(port, name, item[name])
        port.alias = str(tables.get("if_alias", {}).get(str(port.if_index), port.alias or ""))[:400]
        port.updated_at = at
    portmap = {p.if_index: p for p in state.ports}
    if state.fdb_at and at < state.fdb_at:
        tables = {
            k: v
            for k, v in tables.items()
            if k not in {"bridge_ifindex", "vlan_fdb_id", "vlan_fdb_port", "vlan_fdb_status"}
        }
    if complete("bridge_ifindex"):
        previous = {p.bridge_port: p for p in state.bridge_ports}
        state.bridge_ports = [
            previous.get(int(k)) or m.SourceBridgePort(bridge_port=int(k), if_index=int(v))
            for k, v in tables["bridge_ifindex"].items()
            if str(k).isdigit() and str(v).isdigit()
        ]
        for p in state.bridge_ports:
            p.if_index = int(tables["bridge_ifindex"][str(p.bridge_port)])
    bridges = {p.bridge_port: p.if_index for p in state.bridge_ports}
    if complete("vlan_fdb_id"):
        values = {
            int(k.split(".")[-1]): int(v)
            for k, v in tables["vlan_fdb_id"].items()
            if str(k.split(".")[-1]).isdigit() and str(v).isdigit()
        }
        old = {v.vlan_vid: v for v in state.vlan_fdbs}
        state.vlan_fdbs = [
            old.get(vid) or m.SourceVLANFDB(vlan_vid=vid, fdb_id=fid) for vid, fid in values.items()
        ]
        for v in state.vlan_fdbs:
            v.fdb_id = values[v.vlan_vid]
    by_fid = {}
    for v in state.vlan_fdbs:
        by_fid.setdefault(v.fdb_id, set()).add(v.vlan_vid)
    if fresh_fdb and "vlan_fdb_port" in tables and complete("bridge_ifindex"):
        # Partial tables may contribute proven positive rows, never prove absence.
        prior = {(e.fdb_id, e.mac_address, e.port): e for e in state.mac_entries}
        found = {}
        unresolved = False
        for key, bridge in tables["vlan_fdb_port"].items():
            try:
                fid, *octets = map(int, key.split("."))
                if len(octets) != 6:
                    unresolved = True
                    continue
                mac = bytes(octets).hex(":")
                bridge = int(bridge)
                index = bridges.get(bridge, 0)
                port = portmap.get(index)
                name = port.name if port else ""
                status = str(tables.get("vlan_fdb_status", {}).get(key, ""))
                if status in ("2", "4"):
                    continue
                if not name or status not in ("1", "3", "5"):
                    unresolved = True
                    continue
                identity = (fid, mac, name)
                if identity in prior and prior[identity].observed_at and prior[identity].observed_at > at:
                    found[identity] = prior[identity]
                    continue
                e = prior.get(identity) or m.SwitchMacEntry(
                    id=m.uid(),
                    fdb_id=fid,
                    mac_address=mac,
                    port=name,
                    vrf_id=device.vrf_id if device else "",
                    if_index=index,
                )
                e.vlan_vid = next(iter(by_fid[fid])) if len(by_fid.get(fid, ())) == 1 else 0
                e.bridge_port, e.if_index = bridge, index
                e.status = str(tables.get("vlan_fdb_status", {}).get(key, ""))[:10]
                e.observed_at = at
                e.present = True
                found[identity] = e
            except (ValueError, TypeError):
                unresolved = True
                continue
        if unresolved:
            fdb_complete = False
            diagnostic = known.get("vlan_fdb_port")
            if diagnostic and diagnostic.status == "complete":
                diagnostic.status = "incomplete"
                diagnostic.error_code = "unresolved_row_dependencies"
                diagnostic.successful_at = previous_success.get("vlan_fdb_port")
        if fdb_complete:
            state.fdb_at, state.fdb_complete = at, True
        for identity, entry in prior.items():
            if identity not in found:
                if not fdb_complete or (entry.observed_at and entry.observed_at > at):
                    found[identity] = entry
                    continue
                entry.present = False
                # Keep only referenced last-known facts; subsequent collection reclaims others.
                referenced = db.scalar(
                    select(m.ResolutionConnection.id)
                    .where(m.ResolutionConnection.mac_port_id == entry.id)
                    .limit(1)
                )
                if referenced:
                    found[identity] = entry
        state.mac_entries = list(found.values())
        state.entry_count = sum(e.present for e in found.values())
    if (
        complete("ip_addr_ifindex", "ip_addr_mask")
        or complete("ip_address_ifindex", "ip_address_prefix")
        or "_prefixes" in tables
    ):
        old = {(p.if_index, p.address, p.prefix_length): p for p in state.prefixes}
        state.prefixes = [
            old.get(k) or m.SourcePrefix(if_index=k[0], address=k[1], prefix_length=k[2])
            for k in sorted(prefixes(tables))
        ]
    if (
        device
        and (not state.gateway_at or at >= state.gateway_at)
        and ("arp_mac" in tables or "ndp_mac" in tables)
    ):
        gateway_complete = complete("arp_mac", "ndp_mac")
        if gateway_complete:
            state.gateway_at = at
        from types import SimpleNamespace

        from ..ipam.connections import bindings

        found = set()
        for address, mac, index in bindings(tables, unsupported):
            item = gateway(
                db,
                SimpleNamespace(address=address, vrf_id=device.vrf_id),
                dict(device_id=device.id, mac_address=mac, if_index=index),
                at,
            )
            found.add(item.id)
        if gateway_complete and not data.get("partial"):
            for item in db.scalars(
                select(m.GatewayBinding).where(
                    m.GatewayBinding.device_id == device.id, m.GatewayBinding.present.is_(True)
                )
            ):
                if item.id not in found and item.observed_at <= at:
                    item.present = False
    complete = set(data.get("neighbor_protocols_complete") or [])
    if "neighbor_protocols_complete" in data and (not state.neighbors_at or at >= state.neighbors_at):
        state.lldp_complete = "lldp" in complete
        state.cdp_complete = "cdp" in complete
    detail = data.get("neighbor_detail") or {}
    stp = detail.get("spanning_tree") or next(
        (
            n.get("evidence", {}).get("spanning_tree")
            for n in data.get("neighbors", [])
            if n.get("evidence", {}).get("spanning_tree")
        ),
        None,
    )
    if stp:
        state.stp_root, state.stp_port, state.stp_source = (
            stp.get("is_root"),
            stp.get("port"),
            stp.get("source", ""),
        )
    for name, agg in (detail.get("trunks") or {}).items():
        p = port_for(state, name)
        p.aggregate, p.aggregate_type, p.aggregate_source = (
            agg.get("name", ""),
            agg.get("type", ""),
            agg.get("source", ""),
        )
    if device and (not state.neighbors_at or at >= state.neighbors_at) and "neighbors" in data:
        state.neighbors_at = at
        links = list(db.scalars(select(m.Link).where(m.Link.device_id == device.id)))
        links.extend(
            r for r in db.new if isinstance(r, m.Link) and r.device_id == device.id and r not in links
        )
        seen = set()
        for item in data["neighbors"]:
            exact = [
                l
                for l in links
                if l.interface_name == item["interface_name"]
                and l.remote_name == item["remote_name"]
                and l.remote_port == item.get("remote_port", "")
            ]
            if not exact:
                exact = [
                    l
                    for l in links
                    if legacy_match(l, {"source": "lldp", "remote_port": "", **item})
                    or same_neighbor(dict(interface_name=l.interface_name, evidence=l.evidence), item)
                ]
            link = next((l for l in exact if l.auto_add_excluded), None) or (
                exact[0] if len(exact) == 1 else None
            )
            if link is None:
                link = m.Link(
                    id=m.uid(),
                    device_id=device.id,
                    interface_name=item["interface_name"],
                    remote_name=item["remote_name"],
                    remote_port=item.get("remote_port", ""),
                    source=item.get("source", "lldp"),
                )
                db.add(link)
                links.append(link)
            if link.source == "manual":
                continue
            link.evidence = item.get("evidence") or {}
            link.source = item.get("source", "lldp")
            link.remote_name, link.remote_port = item["remote_name"], item.get("remote_port", "")
            link.last_seen_at = at
            link.is_current = not link.auto_add_excluded
            write_neighbor(db, link)
            seen.add(link.id)
        for link in links:
            if (
                link not in db.new
                and (not link.last_seen_at or link.last_seen_at <= at)
                and link.id not in seen
                and link.source != "manual"
                and set((link.source or "").split("+")) <= complete
            ):
                link.is_current = False


def read(state):
    from sqlalchemy.orm import object_session

    db = object_session(state)
    tables = {name: {} for name in ("vlan_fdb_id", "vlan_fdb_port", "vlan_fdb_status", "bridge_ifindex")}
    interfaces = []
    for p in state.ports:
        if p.if_index is None:
            continue
        interfaces.append(
            dict(
                if_index=p.if_index,
                name=p.name,
                description=p.description,
                mac_address=p.mac_address,
                admin_status=p.admin_status,
                oper_status=p.oper_status,
                speed_bps=p.speed_bps,
            )
        )
        for key, value in [
            ("if_name", p.name),
            ("if_descr", p.description or p.name),
            ("if_alias", p.alias),
            ("if_mac", p.mac_address),
            ("if_status", "1" if p.oper_status == "up" else "2"),
            ("if_speed", p.speed_bps),
        ]:
            tables.setdefault(key, {})[str(p.if_index)] = str(value or "")
    for p in state.vlan_fdbs:
        tables["vlan_fdb_id"][str(p.vlan_vid)] = str(p.fdb_id)
    for p in state.bridge_ports:
        tables["bridge_ifindex"][str(p.bridge_port)] = str(p.if_index)
    device = db.get(m.Device, state.device_id) if db and state.device_id else None
    for e in state.mac_entries:
        if device and e.vrf_id != device.vrf_id:
            continue
        if e.vlan_vid and not any(v.vlan_vid == e.vlan_vid and v.fdb_id == e.fdb_id for v in state.vlan_fdbs):
            continue
        if e.present is False:
            continue
        key = str(e.fdb_id) + "." + ".".join(str(int(v, 16)) for v in e.mac_address.split(":"))
        tables["vlan_fdb_port"][key] = str(e.bridge_port or e.if_index)
        tables["vlan_fdb_status"][key] = e.status
        tables["bridge_ifindex"].setdefault(str(e.bridge_port or e.if_index), str(e.if_index))
    tables["_prefixes"] = [
        dict(if_index=p.if_index, address=p.address, prefix_length=p.prefix_length) for p in state.prefixes
    ]
    gateway_rows = []
    if db and state.device_id:
        for g in db.scalars(
            select(m.GatewayBinding).where(
                m.GatewayBinding.device_id == state.device_id, m.GatewayBinding.present.is_(True)
            )
        ):
            gateway_rows.append((g.address, g.mac_address, g.if_index))
            try:
                address = ipaddress.ip_address(g.address)
                if address.version == 4:
                    key = str(g.if_index) + "." + g.address
                    tables.setdefault("arp_mac", {})[key] = g.mac_address
                    tables.setdefault("arp_type", {})[key] = "3"
                else:
                    key = str(g.if_index) + ".2.16." + ".".join(map(str, address.packed))
                    tables.setdefault("ndp_mac", {})[key] = g.mac_address
            except ValueError:
                continue
    neighbors = []
    if db and state.device_id:
        links = list(
            db.scalars(
                select(m.Link).where(
                    m.Link.device_id == state.device_id,
                    (m.Link.is_current.is_(True) | m.Link.auto_add_excluded.is_(True)),
                )
            )
        )
        links.extend(
            r for r in db.new if isinstance(r, m.Link) and r.device_id == state.device_id and r not in links
        )
        for l in links:
            if l.source == "manual":
                continue
            evidence = l.evidence
            neighbors.append(
                dict(
                    interface_name=l.interface_name,
                    remote_name=l.remote_name,
                    remote_port=l.remote_port,
                    source=l.source,
                    observed_at=(l.last_seen_at or l.updated_at).isoformat(),
                    evidence=evidence,
                )
            )
            for protocol, mapping in [
                (
                    "lldp",
                    {
                        "chassis_id": "chassis",
                        "chassis_subtype": "chassis_type",
                        "system_name": "name",
                        "port_id": "port",
                        "port_subtype": "port_type",
                        "port_description": "port_desc",
                    },
                ),
                ("cdp", {"device_id": "name", "port_id": "port", "system_name": "sysname"}),
            ]:
                raw = evidence.get(protocol) or {}
                index = raw.get("index")
                if not index:
                    continue
                for field, suffix in mapping.items():
                    if raw.get(field) is not None:
                        tables.setdefault(protocol + "_" + suffix, {})[str(index)] = str(raw[field])
                if protocol == "lldp" and raw.get("local_port_number"):
                    tables.setdefault("lldp_local_id", {})[str(raw["local_port_number"])] = str(
                        raw.get("local_port_id") or l.interface_name
                    )
                    tables.setdefault("lldp_local_desc", {})[str(raw["local_port_number"])] = l.interface_name
    value = dict(
        _bindings=gateway_rows,
        gateway_at=state.gateway_at.isoformat() if state.gateway_at else None,
        fdb_at=state.fdb_at.isoformat() if state.fdb_at else None,
        failed=state.healthy is False,
        fdb_complete=bool(state.fdb_complete),
        table_reads={
            r.name: dict(
                status=r.status,
                row_count=r.row_count,
                error_code=r.error_code,
                attempted_at=r.attempted_at.isoformat() if r.attempted_at else None,
            )
            for r in state.unsupported
        },
        tables=tables,
        interfaces=interfaces,
        neighbors=neighbors,
        neighbor_protocols_complete=[
            k for k, v in [("lldp", state.lldp_complete), ("cdp", state.cdp_complete)] if v
        ],
        unsupported=sorted({v.name for v in state.unsupported if v.status != "complete"}),
    )
    if state.identity:
        info = state.identity
        value.update(
            {
                k: getattr(info, k)
                for k in ("hostname", "sys_description", "sys_object_id", "uptime", "ip_forwarding")
            }
        )
        value["field_sources"] = {
            k: getattr(info, k + "_source")
            for k in ("vendor", "model", "serial", "kind", "software_version", "location", "system_name")
            if getattr(info, k + "_source")
        }
        value["identity"] = {
            k: getattr(info, k)
            for k in ("vendor", "model", "serial", "kind", "software_version", "location", "system_name")
            if getattr(info, k)
        }
    if state.neighbor_detail_failed:
        value["neighbor_detail_failed"] = state.neighbor_detail_failed
    if state.read_context:
        value["read_context"] = state.read_context
    if state.stp_root is not None:
        value["neighbor_detail"] = {
            "spanning_tree": dict(port=state.stp_port, is_root=state.stp_root, source=state.stp_source)
        }
    return value
