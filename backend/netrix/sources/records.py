"""Upserts and read projections for DNS, ICMP, DHCP, gateway and VMware facts."""

import hashlib
from datetime import datetime
from functools import wraps

from sqlalchemy import select

from .. import models as m
from ..core import now


def source_write(fn):
    @wraps(fn)
    def write(db, *args, **kwargs):
        with db.no_autoflush:
            return fn(db, *args, **kwargs)

    return write


def find(db, model, **keys):
    cache = db.info.setdefault("source_rows", {})
    key = (model, tuple(keys.items()))
    if key in cache:
        return cache[key]
    row = next(
        (
            r
            for r in db.new
            if isinstance(r, model) and all(getattr(r, k, None) == v for k, v in keys.items())
        ),
        None,
    )
    if row is None:
        row = db.scalar(select(model).where(*(getattr(model, k) == v for k, v in keys.items())))
    if row is None:
        row = model(**keys)
        if hasattr(model, "id"):
            row.id = m.uid()
        db.add(row)
    if len(cache) < 20000:
        cache[key] = row
    return row


def integration(db, key):
    return key if key and db.get(m.Integration, key) else None


def stamp(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value or now()


@source_write
def gateway(db, iprow, data, at=None):
    device = data.get("device_id")
    if device:
        db.scalar(select(m.Device.id).where(m.Device.id == device).with_for_update())
    actual = db.get(m.Device, device) if device else None
    key = device or data.get("source_key") or "legacy"
    mac = data.get("mac_address") or ""
    existing = list(
        db.scalars(
            select(m.GatewayBinding).where(
                m.GatewayBinding.source_key == key,
                m.GatewayBinding.vrf_id == iprow.vrf_id,
                m.GatewayBinding.address == iprow.address,
                m.GatewayBinding.mac_address == mac,
            )
        )
    )
    index = data.get("if_index") or next((r.if_index for r in existing if r.if_index), 0)
    row = find(
        db,
        m.GatewayBinding,
        source_key=key,
        vrf_id=iprow.vrf_id,
        address=iprow.address,
        mac_address=mac,
        if_index=index,
    )
    row.device_id = actual.id if actual else None
    row.source_name = "" if actual else str(data.get("device_name") or "")[:190]
    incoming = stamp(at or data.get("observed_at"))
    if row.observed_at and row.observed_at > incoming:
        return row
    state = (
        db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == actual.id))
        if actual
        else None
    )
    row.present = data.get("present", True) and not (
        state and state.gateway_at and state.gateway_at > incoming
    )
    row.observed_at = incoming
    return row


@source_write
def dhcp(db, key, data, address, at=None):
    db.scalar(select(m.Integration.id).where(m.Integration.id == key).with_for_update())
    row = find(
        db,
        m.DHCPBinding,
        source_key=key,
        address=data.get("address") or address,
        mac_address=data.get("mac_address") or "",
    )
    row.integration_id = integration(db, key)
    incoming = stamp(at)
    if row.observed_at and row.observed_at > incoming:
        return row
    for name in ("hostname", "lease_state"):
        setattr(row, name, str(data.get(name) or "")[: 190 if name == "hostname" else 40])
    row.reserved = bool(data.get("reserved", True))
    row.present = data.get("present", True)
    row.observed_at = stamp(at)
    return row


@source_write
def vmware(db, key, data, address="", at=None):
    db.scalar(select(m.Integration.id).where(m.Integration.id == key).with_for_update())
    at = stamp(at)
    is_host = data.get("record_type") == "host"
    host_key = data.get("host_id") if is_host else data.get("vm_host")
    host = None
    fresh_host = True
    if host_key:
        host = find(db, m.VMwareHost, source_key=key, external_id=host_key)
        host.integration_id = integration(db, key)
        fresh_host = not host.observed_at or host.observed_at <= at
        if is_host and fresh_host:
            host.hostname = str(data.get("hostname") or "")[:190]
            host.uuid = str(data.get("host_uuid") or "")[:190]
            host.operating_system = str(data.get("operating_system") or "")[:190]
            host.power_state = str(data.get("power_state") or "")[:40]
        elif fresh_host and data.get("vm_host_name"):
            host.hostname = data["vm_host_name"][:190]
        host.observed_at = max(host.observed_at, at) if host.observed_at else at
    owner_key = str(data.get("host_id") if is_host else data.get("vm_id") or "")
    # A legacy point result may carry only an IP/NIC, not a vCenter managed-object ID.
    # Keep that uncertainty explicit; this never grants identity-match confidence.
    if not owner_key:
        owner_key = (
            "unidentified:"
            + hashlib.sha256((address + "|" + str(data.get("mac_address", ""))).encode()).hexdigest()[:40]
        )
    vm = None
    if not is_host:
        vm = find(db, m.VMwareVM, source_key=key, external_id=owner_key)
        vm.integration_id = integration(db, key)
        fresh_vm = not vm.observed_at or vm.observed_at <= at
        if fresh_vm:
            vm.host = host
        for name in ("hostname", "operating_system", "power_state"):
            if name in data and fresh_vm:
                setattr(vm, name, str(data.get(name) or "")[:190])
        vm.observed_at = max(vm.observed_at, at) if vm.observed_at else at
    elif host is None:
        host = find(db, m.VMwareHost, source_key=key, external_id=owner_key)
        host.integration_id = integration(db, key)
    network = None
    network_keys = ("dvswitch", "dvswitch_name", "vswitch_name", "portgroup_key", "network")
    if any(data.get(k) for k in network_keys):
        identity = "|".join(
            str(data.get(k) or "")
            for k in (
                ("dvswitch", "portgroup_key")
                if data.get("dvswitch")
                else ("vm_host", "vswitch_name", "dvswitch_name", "portgroup_key", "network")
            )
        )
        network = find(
            db, m.VMwareNetwork, source_key=key, external_key=hashlib.sha256(identity.encode()).hexdigest()
        )
        for col, keyname in [
            ("switch_id", "dvswitch"),
            ("switch_name", "dvswitch_name"),
            ("standard_switch", "vswitch_name"),
            ("portgroup_key", "portgroup_key"),
            ("name", "network"),
        ]:
            setattr(network, col, str(data.get(keyname) or "")[:190])
    nic_key = str(
        (data.get("vmkernel_device") or data.get("port") or "unknown")
        if is_host
        else data.get("nic_key") or data.get("mac_address") or "unknown"
    )
    nic = find(db, m.VMwareNIC, source_key=key, owner_key=owner_key, nic_key=nic_key)
    fresh_nic = not nic.observed_at or nic.observed_at <= at
    if not fresh_nic:
        result = find(
            db,
            m.VMwareAddress,
            nic_id=nic.id,
            address=data.get("guest_address") or data.get("host_address") or data.get("address") or "",
        )
        result.nic = nic
        if not result.observed_at:
            result.observed_at, result.present = at, False
        return result
    nic.observed_at = at
    nic.host, nic.vm, nic.network = host if is_host else None, vm, network
    nic.mac_address = str(data.get("mac_address") or "")[:17]
    nic.port = str(data.get("dvport") or data.get("port") or "")[:120]
    if is_host and fresh_host and "physical_nics" in data:
        known = {p.device: p for p in host.physical_nics}
        carries = set(data.get("uplink_nics") or [])
        for item in data["physical_nics"]:
            name = item.get("device") or ""
            if not name:
                continue
            p = known.get(name)
            if p is None:
                p = m.VMwarePhysicalNIC(id=m.uid(), device=name)
                host.physical_nics.append(p)
                known[name] = p
            p.mac_address = item.get("mac_address") or ""
            p.link_up = bool(item.get("link_up"))
            if item.get("carries_ip"):
                carries.add(name)
            old = {(h.protocol, h.chassis_id, h.port_id): h for h in p.hints}
            seen = []
            for hint in item.get("hints") or []:
                hk = (hint.get("protocol", ""), hint.get("chassis_id", ""), hint.get("port_id", ""))
                h = old.get(hk) or m.VMwareHint(id=m.uid(), protocol=hk[0], chassis_id=hk[1], port_id=hk[2])
                h.port_description = hint.get("port_description") or ""
                did = hint.get("device_id")
                h.device_id = did if did and db.get(m.Device, did) else None
                old_addresses = {a.address: a for a in h.addresses}
                h.addresses = [
                    old_addresses.get(a) or m.VMwareHintAddress(address=a)
                    for a in sorted(set(hint.get("addresses") or []))
                ]
                seen.append(h)
            p.hints = seen
        nic.uplinks = [m.VMwareUplink(physical_nic=known[name]) for name in sorted(carries) if name in known]
    addr = data.get("guest_address") or data.get("host_address") or data.get("address") or ""
    result = find(db, m.VMwareAddress, nic_id=nic.id, address=addr)
    result.nic = nic
    result.present = data.get("present", True)
    result.observed_at = at
    return result


def vmware_data(row):
    n = row.nic
    if not n:
        return {}
    owner = n.host or n.vm
    if not owner:
        return {}
    d = dict(
        integration_id=n.source_key,
        mac_address=n.mac_address or "",
        hostname=owner.hostname or "",
        operating_system=owner.operating_system or "",
        power_state=owner.power_state or "",
        present=row.present,
    )
    if n.host:
        host = n.host
        carries = {u.physical_nic.device for u in n.uplinks}
        d.update(
            record_type="host",
            host_id=host.external_id,
            host_uuid=host.uuid,
            host_address=row.address,
            vmkernel_device=n.nic_key,
            uplink_nics=sorted(carries),
            physical_nics=[],
        )
        for p in host.physical_nics:
            hints = []
            for h in p.hints:
                hint = dict(
                    protocol=h.protocol,
                    chassis_id=h.chassis_id,
                    port_id=h.port_id,
                    port_description=h.port_description,
                    addresses=[a.address for a in h.addresses],
                )
                if h.device_id:
                    hint["device_id"] = h.device_id
                hints.append(hint)
            d["physical_nics"].append(
                dict(
                    device=p.device,
                    mac_address=p.mac_address,
                    link_up=p.link_up,
                    carries_ip=p.device in carries,
                    hints=hints,
                )
            )
    else:
        d.update(
            vm_id=n.vm.external_id if not n.vm.external_id.startswith("unidentified:") else "",
            nic_key=n.nic_key,
            guest_address=row.address,
            dvport=n.port or "",
            vm_host=n.vm.host.external_id if n.vm.host else "",
            vm_host_name=n.vm.host.hostname if n.vm.host else "",
        )
    if n.network:
        net = n.network
        d.update(
            network=net.name,
            portgroup_key=net.portgroup_key,
            dvswitch=net.switch_id,
            dvswitch_name=net.switch_name,
            vswitch_name=net.standard_switch,
        )
    return d


def observation_data(row):
    d = {}
    if row.dns:
        d = {"hostname": row.dns.hostname or ""}
    elif row.ping:
        d = {"reachability": row.ping.reachability or "unknown"}
    elif row.dhcp:
        d = {k: getattr(row.dhcp, k) for k in ("hostname", "mac_address", "reserved", "lease_state")}
        d["integration_id"] = row.dhcp.source_key
        d["address"] = row.dhcp.address
    elif row.vmware:
        d = vmware_data(row.vmware)
    elif row.gateway:
        g = row.gateway
        d = dict(
            mac_address=g.mac_address,
            device_id=g.device_id or g.source_key,
            device_name=g.source_name,
            if_index=g.if_index,
        )
    elif row.network:
        d = dict(
            address_scope=[row.scope_address, row.scope_vrf, row.scope_vlan],
            device_address=row.network.address,
            read_context=row.network.read_context,
            observation_id=row.network.id,
        )
    if row.matched_by:
        d["matched_by"] = row.matched_by
    fact = row.dhcp or row.vmware or row.gateway
    if row.present is False or (fact is not None and fact.present is False):
        d["present"] = False
    return d


@source_write
def write_observation(db, row, data):
    iprow = db.get(m.IPAddress, row.address_id) or next(
        (r for r in db.new if isinstance(r, m.IPAddress) and r.id == row.address_id), None
    )
    if iprow is None:
        raise ValueError("Source link requires an existing IP")
    row.present = data.get("present", True)
    if row.present is False and (row.vmware or row.dhcp or row.dns or row.ping):
        return
    row.matched_by = data.get("matched_by") or ""
    if row.source == "dns":
        row.dns = find(db, m.DNSRecord, address_id=row.address_id, source_key=row.source_key)
        row.dns.hostname = str(data.get("hostname") or "")[:190]
        # A successful read refreshes this canonical record even when the value is unchanged.
        row.dns.updated_at = row.observed_at
    elif row.source == "icmp":
        row.ping = find(db, m.PingState, address_id=row.address_id)
        row.ping.reachability = data.get("reachability", "unknown")
    elif row.source == "windows_dhcp":
        row.dhcp = dhcp(
            db, data.get("integration_id") or row.source_key, data, iprow.address, row.observed_at
        )
    elif row.source == "vcenter":
        key = data.get("integration_id") or row.source_key.split(":")[0]
        row.vmware = vmware(db, key, data, iprow.address, row.observed_at)
    elif row.source == "gateway":
        row.gateway = gateway(db, iprow, data, row.observed_at)
    elif row.source in ("ipam_network", "address_network"):
        from .network import state_for

        device = db.get(m.Device, row.source_key)
        row.network = state_for(
            db, row.source_key, data.get("device_address") or (device.management_ip if device else "")
        )
        if data.get("address_scope"):
            row.scope_address, row.scope_vrf, row.scope_vlan = data["address_scope"]
    elif data:
        raise ValueError("Unsupported persisted source type: " + row.source)


@source_write
def save_integration(db, config, values, *, complete=False):
    """One writer for full and target-only results; absence is authoritative only in full reads."""
    seen = set()
    owners = {}
    if config.kind == "vcenter":
        for item in values:
            native = item.get("host_id") if item.get("record_type") == "host" else item.get("vm_id")
            key = (item.get("record_type", "vm"), native)
            name = (item.get("hostname") or "").casefold().rstrip(".")
            if native and name:
                if key in owners and owners[key] != name:
                    raise ValueError("VMware snapshot contains conflicting native owner names")
                owners[key] = name
    collected_at = now()
    for item in values:
        record = (
            vmware(db, config.id, item, item.get("address", ""), collected_at)
            if config.kind == "vcenter"
            else dhcp(db, config.id, item, item.get("address", ""), collected_at)
        )
        seen.add(record.id)
    if complete:
        if config.kind == "vcenter":
            rows = db.scalars(
                select(m.VMwareAddress).join(m.VMwareNIC).where(m.VMwareNIC.source_key == config.id)
            )
        else:
            rows = db.scalars(select(m.DHCPBinding).where(m.DHCPBinding.source_key == config.id))
        for row in rows:
            if row.id not in seen:
                row.present = False
    return len(seen)
