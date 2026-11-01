"""Read-only IPAM attachment resolution. Never imports devices or mutates topology."""

import ipaddress
from collections import defaultdict
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select

from .. import models as m
from ..core import now
from ..discovery.visibility import inventory_links


def network_device(device):
    kind = (device.device_type.name if device.device_type else device.kind).casefold()
    return device.kind in {"switch", "router", "firewall"} or kind in {
        "switch",
        "router",
        "firewall",
        "backbone",
        "backbone switch",
        "corner switch",
        "san switch",
    }


def integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def ip(value):
    try:
        return str(ipaddress.ip_address(value))
    except (ValueError, TypeError):
        return None


def bindings(tables, unsupported):
    """ARP/NDP interface, address and unicast MAC; incomplete entries are not identities."""
    from .service import normalized_mac

    result = []
    for key in ("arp_mac", "ndp_mac"):
        if key in unsupported:
            continue
        for index, value in tables.get(key, {}).items():
            try:
                parts = [int(p) for p in index.split(".")]
                if key == "arp_mac":
                    if len(parts) != 5 or tables.get("arp_type", {}).get(index) in ("1", "2"):
                        continue
                    address = str(ipaddress.IPv4Address(bytes(parts[1:])))
                else:
                    if (
                        len(parts) < 3
                        or (parts[1], parts[2]) not in ((1, 4), (2, 16))
                        or len(parts[3:]) != parts[2]
                    ):
                        continue
                    if tables.get("ndp_state", {}).get(index) in ("5", "6", "7") or tables.get(
                        "ndp_type", {}
                    ).get(index) in ("1", "2"):
                        continue
                    address = str(ipaddress.ip_address(bytes(parts[3:])))
                mac = normalized_mac(value)
                if mac and not int(mac[:2], 16) & 1:
                    result.append((address, mac, parts[0]))
            except (ValueError, TypeError):
                continue
    return result


def project(evidence):
    """Map Q-BRIDGE FDB IDs through the VLAN table; FDB ID is not VLAN ID."""
    tables = evidence.get("tables") or {}
    unsupported = set(evidence.get("unsupported") or [])
    interfaces = {integer(p.get("if_index")): p for p in evidence.get("interfaces", [])}
    fids = defaultdict(set)
    for index, fid in tables.get("vlan_fdb_id", {}).items():
        vid = integer(index.split(".")[-1])
        if vid is not None and 1 <= vid <= 4094 and integer(fid) is not None:
            fids[str(fid)].add(vid)
    fdb = defaultdict(set)
    population = defaultdict(set)
    if not unsupported.intersection({"vlan_fdb_port", "vlan_fdb_status", "vlan_fdb_id", "bridge_ifindex"}):
        for index, bridge in tables.get("vlan_fdb_port", {}).items():
            try:
                fid, *octets = index.split(".")
                if len(octets) != 6 or tables.get("vlan_fdb_status", {}).get(index) not in ("3", "5"):
                    continue
                mac = bytes(int(v) for v in octets).hex(":")
                interface = interfaces.get(integer(tables.get("bridge_ifindex", {}).get(str(bridge))))
                if not interface or interface.get("oper_status") != "up" or not interface.get("name"):
                    continue
                population[interface["name"]].add(mac)
                # Shared filtering databases cannot establish a unique VLAN.
                if len(fids[fid]) != 1:
                    continue
                vid = next(iter(fids[fid]))
                fdb[(vid, mac)].add(interface["name"])
            except (ValueError, TypeError):
                continue
    addresses = defaultdict(list)
    for address, mac, index in bindings(tables, unsupported):
        addresses[address].append((mac, index))
    return {
        "bindings": addresses,
        "fdb": fdb,
        "population": population,
        "tables": tables,
        "unsupported": unsupported,
        "interfaces": interfaces,
        "evidence": evidence,
    }


def gateway_interfaces(tables, network):
    attached = set()
    for key, index in tables.get("ip_addr_ifindex", {}).items():
        try:
            address = tables.get("ip_addr_address", {}).get(key, key)
            subnet = ipaddress.ip_network(f"{address}/{tables['ip_addr_mask'][key]}", strict=False)
            if subnet.version == network.version and subnet.prefixlen and network.subnet_of(subnet):
                attached.add(integer(index))
        except (KeyError, ValueError):
            continue
    # RFC 4293 ipAddressPrefix points at a row indexed by interface, family,
    # prefix octets and prefix length. This also proves IPv6 attachment.
    for key, index in tables.get("ip_address_ifindex", {}).items():
        pointer = tables.get("ip_address_prefix", {}).get(key, "")
        base = "1.3.6.1.2.1.4.32.1.5."
        if not str(pointer).lstrip(".").startswith(base):
            continue
        try:
            parts = [int(v) for v in str(pointer).lstrip(".")[len(base) :].split(".")]
            length = {1: 4, 2: 16}.get(parts[1])
            if not length:
                continue
            # Standard variable-length InetAddress indexes include length.
            # FortiOS encodes these RowPointers without that octet count.
            octets = (
                parts[3:-1]
                if len(parts) == length + 4 and parts[2] == length
                else parts[2:-1]
                if len(parts) == length + 3
                else []
            )
            if len(octets) != length:
                continue
            subnet = ipaddress.ip_network((ipaddress.ip_address(bytes(octets)), parts[-1]), strict=False)
            if (
                parts[0] == integer(index)
                and subnet.version == network.version
                and subnet.prefixlen
                and network.subnet_of(subnet)
            ):
                attached.add(parts[0])
        except (IndexError, ValueError, TypeError):
            continue
    return attached


class Evidence:
    def __init__(self, db, vrfs):
        self.at = now()
        self.devices = {
            d.id: d
            for d in db.scalars(
                select(m.Device).where(
                    m.Device.vrf_id.in_(vrfs),
                    m.Device.archived.is_(False),
                    m.Device.discovery_scope_id.is_not(None),
                    m.Device.lifecycle_status.in_(("active", "maintenance")),
                )
            )
            if network_device(d)
        }
        self.snapshots = {}
        if not self.devices:
            self.links = []
            return
        # A newer empty/failed snapshot supersedes old positive evidence. Pick
        # latest before checking age/content so stale locations cannot reappear.
        ranked = (
            select(
                m.Observation.id,
                func.row_number()
                .over(
                    partition_by=m.Observation.device_id,
                    order_by=(m.Observation.created_at.desc(), m.Observation.id.desc()),
                )
                .label("position"),
            )
            .where(m.Observation.device_id.in_(self.devices), m.Observation.source == "ipam_network")
            .subquery()
        )
        for obs in db.scalars(
            select(m.Observation).join(ranked, ranked.c.id == m.Observation.id).where(ranked.c.position == 1)
        ):
            if obs.address == self.devices[obs.device_id].management_ip:
                self.snapshots[obs.device_id] = (obs, project(obs.evidence))
        self.links = list(
            db.scalars(
                select(m.Link).where(
                    m.Link.device_id.in_(self.devices),
                    m.Link.is_current.is_(True),
                    m.Link.auto_add_excluded.is_(False),
                    inventory_links(),
                )
            )
        )

    def resolve(self, row, vlan):
        lifetime = timedelta(seconds=max(300, min(vlan.discovery_interval * 2, 86400)))
        cutoff = self.at - lifetime
        snapshots = {
            id: (o, p)
            for id, (o, p) in self.snapshots.items()
            if o.created_at >= cutoff and self.devices[id].vrf_id == row.vrf_id
        }
        network = ipaddress.ip_network(vlan.cidr)
        gateway = []
        for id, (obs, p) in snapshots.items():
            device = self.devices[id]
            # The address must be on a directly attached gateway interface.
            # A management host's ARP cache is not a gateway source.
            if device.kind not in ("router", "firewall") and str(p["evidence"].get("ip_forwarding")) != "1":
                continue
            attached = gateway_interfaces(p["tables"], network)
            for mac, index in p["bindings"].get(row.address, ()):
                if index in attached:
                    gateway.append(
                        {
                            "device_id": id,
                            "device_name": device.name,
                            "mac_address": mac,
                            "source": "gateway",
                            "observed_at": obs.created_at.isoformat(),
                        }
                    )
        macs = {g["mac_address"] for g in gateway}
        links = []
        for link in self.links:
            if (
                self.devices[link.device_id].vrf_id != row.vrf_id
                or not link.last_seen_at
                or link.last_seen_at < cutoff
            ):
                continue
            links.append(
                (
                    link.device_id,
                    link.interface_name,
                    link.remote_device_id,
                    link.evidence or {},
                    link.last_seen_at,
                    link.id,
                )
            )
        candidates = {}
        blocked = set()
        for id, (_, p) in snapshots.items():
            for n in p["evidence"].get("neighbors", []):
                for port in (
                    n.get("interface_name"),
                    (n.get("evidence", {}).get("local_aggregate") or {}).get("name"),
                ):
                    if port:
                        blocked.add((id, port))
        identities = defaultdict(list)
        direct = []
        identity_conflict = False
        for id, port, remote, data, when, proof_id in links:
            if not port:
                continue
            aggregate = (data.get("local_aggregate") or {}).get("name")
            blocked.update((id, p) for p in (port, aggregate) if p)
            lldp = data.get("lldp") or {}
            from .service import normalized_mac

            advertised = {
                normalized_mac(lldp.get("chassis_id")) if lldp.get("chassis_subtype") == 4 else "",
                normalized_mac(lldp.get("port_id")) if lldp.get("port_subtype") == 3 else "",
            } - {""}
            address_match = any(
                ip((data.get(protocol) or {}).get("management_address")) == row.address
                for protocol in ("lldp", "cdp")
            )
            snapshot = snapshots.get(id)
            if snapshot and snapshot[0].created_at >= when:
                interfaces = snapshot[1]["interfaces"].values()
                if any(p.get("name") == port and p.get("oper_status") == "down" for p in interfaces):
                    continue
            uuid = None
            try:
                if lldp.get("chassis_subtype") == 7:
                    uuid = str(UUID(lldp.get("chassis_id", "")))
            except (ValueError, TypeError, AttributeError):
                pass
            candidate = {
                "device_id": id,
                "device_name": self.devices[id].name,
                "port": port,
                "aggregate": aggregate,
                "source": "neighbors",
                "observed_at": when.isoformat(),
                "evidence_id": proof_id,
                "endpoint_identity": uuid,
                "confidence": 0.95,
            }
            if uuid:
                identities[uuid].append(candidate)
            if address_match or (len(macs) == 1 and advertised & macs):
                if address_match and len(macs) == 1 and advertised and not advertised & macs:
                    identity_conflict = True
                    continue
                # A known infrastructure peer is transit unless its advertised IP
                # is the requested IP itself.
                if remote not in self.devices or address_match:
                    direct.append(candidate)
        for candidate in direct:
            group = (
                identities[candidate["endpoint_identity"]] if candidate["endpoint_identity"] else [candidate]
            )
            for c in group:
                candidates[(c["device_id"], c["port"])] = c
        if not direct and len(macs) == 1:
            mac = next(iter(macs))
            for id, (obs, p) in snapshots.items():
                if not p["evidence"].get("neighbor_protocols_complete"):
                    continue
                names = {p.get("name") for p in p["interfaces"].values()}
                if any(n.get("interface_name") not in names for n in p["evidence"].get("neighbors", [])):
                    # An unresolved LLDP local port could be the FDB uplink.
                    # Do not infer an edge until every advertised port is mapped.
                    continue
                for port in p["fdb"].get((vlan.vid, mac), ()):
                    # Multi-MAC ports may hide another bridge, phone or hypervisor.
                    # They are not evidence of a direct endpoint attachment.
                    if (id, port) in blocked or p["population"].get(port) != {mac}:
                        continue
                    candidates[(id, port)] = {
                        "device_id": id,
                        "device_name": self.devices[id].name,
                        "port": port,
                        "aggregate": None,
                        "source": "gateway+vlan_fdb",
                        "observed_at": obs.created_at.isoformat(),
                        "evidence_id": obs.id,
                        "endpoint_identity": None,
                        "confidence": 0.85,
                    }
        values = sorted(candidates.values(), key=lambda c: (c["device_name"], c["port"]))
        identities = {c["endpoint_identity"] for c in values}
        aggregates = {(c["device_id"], c["aggregate"]) for c in values}
        grouped = len(values) > 1 and (
            (len(identities) == 1 and None not in identities)
            or (len(aggregates) == 1 and values[0]["aggregate"])
        )
        ambiguous = identity_conflict or len(macs) > 1 or (len(values) > 1 and not grouped)
        accepted = values if not ambiguous else []
        groups = {}
        for c in accepted:
            group = groups.setdefault(
                c["device_id"], {"device_id": c["device_id"], "device_name": c["device_name"], "ports": []}
            )
            group["ports"].append(c["port"])
        for g in groups.values():
            g["port_label"] = " / ".join(g["ports"])
        reason = (
            "Çelişkili gateway MAC kayıtları"
            if len(macs) > 1
            else "Gateway ve komşuluk kimliği çelişiyor"
            if identity_conflict
            else "Birden fazla bağımsız bağlantı adayı"
            if ambiguous
            else ""
            if accepted
            else "Güncel ve tekil bağlantı kanıtı bulunamadı"
        )
        return {
            "mac_address": next(iter(macs)) if len(macs) == 1 else "",
            "mac_conflict": len(macs) > 1,
            "gateway_evidence": gateway,
            "connections": values,
            "connection_groups": list(groups.values()),
            "connected_device": " / ".join(g["device_name"] for g in groups.values()),
            "connected_port": " / ".join(g["port_label"] for g in groups.values()),
            "connection_type": "physical" if accepted else "",
            "connection_ambiguous": bool(ambiguous),
            "connection_reason": reason,
        }
