"""Resolution decisions reference canonical facts; no copied hostnames, MACs or ports."""

from sqlalchemy import select
from sqlalchemy.orm import object_session

from .. import models as m
from ..core import now
from . import records
from .records import source_write


def connection_data(row):
    db = object_session(row)
    if row.vmware_nic:
        nic = row.vmware_nic
        net = nic.network
        if not net:
            return None
        return dict(
            device_id=net.switch_id or net.switch_name or net.standard_switch,
            device_name=net.switch_name or net.standard_switch,
            port=nic.port or "",
            aggregate="",
            source=row.source,
            confidence=row.confidence,
            observed_at=nic.observed_at.isoformat(),
        )
    if row.neighbor:
        link = row.neighbor
        device = db.get(m.Device, link.device_id) if db else None
        return dict(
            device_id=link.device_id,
            device_name=device.name if device else "",
            port=link.interface_name,
            remote_port=link.remote_port,
            aggregate=link.aggregate or "",
            source=row.source,
            confidence=row.confidence,
            endpoint_identity=row.endpoint_identity or None,
            observed_at=(link.last_seen_at or link.updated_at).isoformat(),
        )
    if row.mac_port:
        e = row.mac_port
        state = db.get(m.IPAMNetworkState, e.snapshot_id) if db else None
        device = db.get(m.Device, state.device_id) if db and state and state.device_id else None
        return dict(
            device_id=state.device_id if state else "",
            device_name=device.name if device else "",
            port=e.port,
            aggregate="",
            source=row.source,
            confidence=row.confidence,
            primary_source=row.primary_source,
            endpoint_identity=row.endpoint_identity or None,
            observed_at=e.observed_at.isoformat(),
        )
    return None


def read(row):
    from ..ipam.pipeline import groups

    db = object_session(row)
    cache = db.info.get("resolution_views") if db else None
    if cache is not None and row.id in cache:
        return cache[row.id]
    values = dict(
        hostname="",
        mac_address="",
        operating_system="",
        connected_device="",
        connected_port="",
        network="",
        power_state="",
        connection_type=row.connection_type or "",
        field_sources={},
        gateway_evidence=[],
        connections=[],
        connection_groups=[],
        observations=[],
        cached_import=bool(row.cached_import),
    )
    links = db.info.get("source_links_by_ip", {}).get(row.address_id) if db else []
    if links is None:
        links = list(db.scalars(select(m.IPObservation).where(m.IPObservation.address_id == row.address_id)))
    for entry in row.fields:
        value = ""
        if entry.gateway:
            value = entry.gateway.mac_address
        elif entry.source_link:
            data = entry.source_link.data
            value = data.get(entry.field, "")
            if entry.field == "network":
                value = data.get("network", "")
        values[entry.field] = value
        if entry.source:
            values["field_sources"][entry.field] = entry.source
    if row.hostname_conflict:
        values["hostname"] = "YANLIŞ-DHCP-VERİSİ"
        values["field_sources"]["hostname"] = "windows_dhcp"
    for link in links:
        if link.source == "icmp":
            continue
        values["observations"].append(
            dict(
                id=link.id,
                source=link.source,
                source_key=link.source_key,
                observed_at=link.observed_at.isoformat(),
                data=link.data,
            )
        )
        if link.gateway:
            g = link.gateway
            device = db.get(m.Device, g.device_id) if db and g.device_id else None
            values["gateway_evidence"].append(
                dict(
                    device_id=g.device_id or g.source_key,
                    device_name=device.name if device else g.source_name,
                    mac_address=g.mac_address,
                    source="gateway",
                    observed_at=g.observed_at.isoformat(),
                )
            )
    for item in row.connection_rows:
        data = connection_data(item)
        if data:
            values["connections"].append(data)
    values["connection_groups"] = groups(values["connections"])
    values["connected_device"] = " / ".join(g["device_name"] for g in values["connection_groups"])
    values["connected_port"] = " / ".join(g["port_label"] for g in values["connection_groups"])
    vms = [o.vmware for o in links if o.vmware and o.present and o.vmware.present]
    if vms:
        values["vm_ids"] = [
            dict(integration_id=v.nic.source_key, vm_id=v.nic.vm.external_id) for v in vms if v.nic.vm
        ]
        hosts = [v for v in vms if v.nic.host]
        if hosts:
            h = records.vmware_data(hosts[0])
            values["physical_nics"] = h["physical_nics"]
            values["vmware_host"] = {
                k: h.get(k) for k in ("host_id", "host_uuid", "hostname", "vmkernel_device")
            }
    if cache is not None:
        cache[row.id] = values
    return values


def source_key(source, data, index):
    key = data.get("integration_id") or data.get("device_id") or source
    if source == "vcenter":
        if data.get("record_type") == "host":
            key += ":host:" + str(data.get("host_id", "")) + ":" + str(data.get("vmkernel_device", ""))
        elif data.get("vm_id"):
            key += ":" + str(data["vm_id"]) + ":" + str(data.get("nic_key", ""))
    return key[:120]


@source_write
def write(db, result, value):
    from .network import state_for

    iprow = db.get(m.IPAddress, result.address_id) or next(
        (r for r in db.new if isinstance(r, m.IPAddress) and r.id == result.address_id), None
    )
    if iprow is None:
        raise ValueError("Resolution requires an IP")
    obs = list(db.scalars(select(m.IPObservation).where(m.IPObservation.address_id == iprow.id)))
    obs.extend(
        o for o in db.new if isinstance(o, m.IPObservation) and o.address_id == iprow.id and o not in obs
    )
    if value.get("_sql_only"):
        for ref in value.get("_sql_refs", []):
            model, relation = {
                "gateway": (m.GatewayBinding, "gateway"),
                "vcenter": (m.VMwareAddress, "vmware"),
                "windows_dhcp": (m.DHCPBinding, "dhcp"),
                "dns": (m.DNSRecord, "dns"),
            }[ref["kind"]]
            fact = db.get(model, ref["id"])
            if fact is None:
                continue
            link = next(
                (o for o in obs if o.source == ref["kind"] and o.source_key == ref["source_key"]), None
            )
            if link is None:
                link = m.IPObservation(
                    id=m.uid(), address_id=iprow.id, source=ref["kind"], source_key=ref["source_key"]
                )
                db.add(link)
                obs.append(link)
            setattr(link, relation, fact)
            link.present = True
            link.observed_at = records.stamp(ref["observed_at"])
    for i, item in enumerate(value.get("observations", [])):
        if value.get("_sql_only") and item["source"] != "dns":
            continue
        source = item["source"]
        if source not in ("dns", "icmp", "vcenter", "windows_dhcp", "gateway"):
            continue
        data = item.get("data") or {}
        # Missing PTR / DNS failure is not evidence that the last valid name changed.
        # Keep its canonical row and observation time for retained results.
        if source == "dns" and not data.get("hostname"):
            continue
        key = source_key(source, data, i)
        if source == "dns":
            key = item.get("source_key") or "system"
        link = next((o for o in obs if o.id == item.get("id")), None) or next(
            (o for o in obs if o.source == source and o.source_key == key), None
        )
        if link is None:
            link = m.IPObservation(id=m.uid(), address_id=iprow.id, source=source, source_key=key)
            db.add(link)
            obs.append(link)
        link.observed_at = records.stamp(item.get("observed_at"))
        records.write_observation(db, link, data)
    for i, data in enumerate([] if value.get("_sql_only") else value.get("gateway_evidence") or []):
        g = records.gateway(db, iprow, data, data.get("observed_at"))
        link = next((o for o in obs if o.source == "gateway" and o.source_key == g.source_key), None)
        if link is None:
            link = m.IPObservation(id=m.uid(), address_id=iprow.id, source="gateway", source_key=g.source_key)
            db.add(link)
            obs.append(link)
        link.gateway = g
        link.observed_at = g.observed_at
        link.present = True
    if (
        not value.get("_sql_only")
        and value.get("mac_address")
        and value.get("field_sources", {}).get("mac_address") == "gateway"
        and not any(o.gateway and o.gateway.mac_address == value["mac_address"] for o in obs)
    ):
        g = records.gateway(
            db,
            iprow,
            dict(source_key="unidentified_gateway", mac_address=value["mac_address"]),
            result.completed_at or now(),
        )
        link = records.find(
            db, m.IPObservation, address_id=iprow.id, source="gateway", source_key=g.source_key
        )
        link.gateway = g
        link.present = True
        link.observed_at = g.observed_at
        if link not in obs:
            obs.append(link)
    result.cached_import = bool(value.get("cached_import"))
    result.hostname_conflict = value.get("hostname") == "YANLIŞ-DHCP-VERİSİ"
    result.connection_type = value.get("connection_type") or ""
    previous = {f.field: f for f in result.fields}
    fields = []
    for field in ("hostname", "mac_address", "operating_system", "network", "power_state"):
        wanted = value.get(field)
        if not wanted or (field == "hostname" and result.hostname_conflict):
            continue
        source = value.get("field_sources", {}).get(field)
        if not source:
            allowed = {"hostname": ("dns", "vcenter", "windows_dhcp"), "operating_system": ("vcenter",)}.get(
                field, ()
            )
            source = next(
                (
                    kind
                    for kind in allowed
                    if any(
                        o.source == kind and o.present is not False and o.data.get(field) == wanted
                        for o in obs
                    )
                ),
                None,
            )
        if field in ("network", "power_state"):
            source = "vcenter"
        if not source and field == "mac_address":
            source = "gateway"
        candidates = [
            o for o in obs if o.source == source and o.present is not False and o.data.get(field) == wanted
        ]
        entry = previous.get(field) or m.ResolutionField(field=field)
        entry.source = source or ""
        entry.source_link = None
        entry.gateway = None
        if candidates:
            entry.source_link = max(candidates, key=lambda o: o.observed_at or now())
        elif source == "gateway":
            matches = [o.gateway for o in obs if o.gateway and o.gateway.mac_address == wanted]
            if not matches:
                matches = list(
                    db.scalars(
                        select(m.GatewayBinding).where(
                            m.GatewayBinding.vrf_id == iprow.vrf_id,
                            m.GatewayBinding.address == iprow.address,
                            m.GatewayBinding.mac_address == wanted,
                        )
                    )
                )
            if matches:
                entry.gateway = max(matches, key=lambda g: g.observed_at or now())
        if entry.source_link or entry.gateway:
            fields.append(entry)
    result.fields = fields
    # IPAM can reference inventory facts, never create a replacement MAC-port row.
    inventory_only = value.get("_sql_only") or value.get("_inventory_switches_only")
    old = {(r.neighbor_id, r.mac_port_id, r.vmware_nic_id): r for r in result.connection_rows}
    rows = []
    connections = value.get("connections") or []
    if not connections and value.get("connected_device") and result.connection_type == "vcenter":
        # Older materializations kept only the virtual switch/port label.
        # Recover the relation from an existing native NIC, never invent a VM
        # or choose a physical inventory device by that display label.
        choices = {
            o.vmware.nic.id: o.vmware.nic
            for o in obs
            if o.vmware
            and o.vmware.nic.network
            and (o.vmware.nic.network.switch_name or o.vmware.nic.network.standard_switch)
            == value["connected_device"]
            and o.vmware.nic.port == str(value.get("connected_port") or "")
        }
        if len(choices) == 1:
            nic = next(iter(choices.values()))
            connections = [
                dict(
                    device_name=value["connected_device"],
                    port=nic.port,
                    source="vcenter",
                    confidence=1.0,
                )
            ]
    if not connections and value.get("connected_device") and value.get("mac_address"):
        matches = list(
            db.execute(
                select(m.Device, m.SwitchMacEntry)
                .join(m.IPAMNetworkState, m.IPAMNetworkState.device_id == m.Device.id)
                .join(m.SwitchMacEntry, m.SwitchMacEntry.snapshot_id == m.IPAMNetworkState.id)
                .where(
                    m.Device.vrf_id == iprow.vrf_id,
                    m.Device.name == value["connected_device"],
                    m.SwitchMacEntry.mac_address == value["mac_address"],
                    *(
                        [m.SwitchMacEntry.port == value["connected_port"]]
                        if value.get("connected_port")
                        else []
                    ),
                )
            )
        )
        if len(matches) == 1:
            device, fact = matches[0]
            connections = [
                dict(device_id=device.id, device_name=device.name, port=fact.port, source="gateway+vlan_fdb")
            ]
    used = set()
    for c in connections:
        neighbor = macport = nic = None
        if c.get("source") == "vcenter" or result.connection_type == "vcenter":
            choices = [
                o.vmware.nic
                for o in obs
                if o.vmware
                and o.vmware.nic.network
                and (o.vmware.nic.network.switch_name or o.vmware.nic.network.standard_switch)
                == c.get("device_name")
                and o.vmware.nic.port == str(c.get("port", ""))
            ]
            nic = choices[0] if choices else None
        else:
            did = c.get("device_id")
            device = db.get(m.Device, did) if did else None
            if device:
                matches = list(
                    db.scalars(
                        select(m.Link).where(m.Link.device_id == did, m.Link.interface_name == c["port"])
                    )
                )
                matches.extend(
                    o
                    for o in db.new
                    if isinstance(o, m.Link)
                    and o.device_id == did
                    and o.interface_name == c["port"]
                    and o not in matches
                )
                exact = [
                    l
                    for l in matches
                    if (value.get("hostname") or "").casefold().rstrip(".")
                    in {
                        l.remote_name.casefold().rstrip("."),
                        (l.manual_remote_name or "").casefold().rstrip("."),
                    }
                ]
                if exact:
                    neighbor = max(exact, key=lambda l: l.last_seen_at or l.updated_at or now())
                elif len(matches) == 1 and c.get("source") in (
                    "neighbors",
                    "nic_teaming",
                    "ipam_ssh_neighbors",
                    "vcenter_host+neighbors",
                ):
                    neighbor = matches[0]
                if not neighbor:
                    state = (
                        db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == did))
                        if inventory_only
                        else state_for(db, did, device.management_ip)
                    )
                    if state is None:
                        continue
                    mac = value.get("mac_address") or ""
                    candidates = [
                        e for e in state.mac_entries if e.mac_address == mac and e.port == c["port"]
                    ]
                    if candidates:
                        macport = max(candidates, key=lambda e: e.observed_at or now())
                    elif mac and not inventory_only:
                        # Retain a last-known fact from the old result when its current
                        # source has already aged out. It is not a new network observation.
                        macport = m.SwitchMacEntry(
                            id=m.uid(),
                            vrf_id=iprow.vrf_id,
                            vlan_vid=(db.get(m.VLAN, iprow.vlan_id).vid if iprow.vlan_id else 0),
                            fdb_id=0,
                            mac_address=mac,
                            port=c["port"],
                            if_index=0,
                            bridge_port=0,
                            status="",
                            observed_at=records.stamp(c.get("observed_at")),
                            present=False,
                        )
                        state.mac_entries.append(macport)
        if not (neighbor or macport or nic):
            continue
        key = (neighbor.id if neighbor else None, macport.id if macport else None, nic.id if nic else None)
        if key in used:
            continue
        used.add(key)
        ref = old.get(key) or m.ResolutionConnection(id=m.uid())
        ref.neighbor, ref.mac_port, ref.vmware_nic = neighbor, macport, nic
        ref.source = c.get("source") or result.connection_type
        ref.confidence = c.get("confidence", 0.5)
        ref.primary_source = c.get("primary_source") or ""
        ref.endpoint_identity = c.get("endpoint_identity") or ""
        rows.append(ref)
    result.connection_rows = rows
