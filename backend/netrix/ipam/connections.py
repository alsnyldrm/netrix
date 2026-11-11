"""Read-only IPAM attachment resolution. Never imports devices or mutates topology."""

import ipaddress
from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import load_only

from .. import models as m
from ..core import now
from ..discovery.visibility import inventory_links
from .fdb_path import backbone, routed_ports


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


@lru_cache(maxsize=65536)
def _ip(value):
    try:
        return str(ipaddress.ip_address(value))
    except (ValueError, TypeError):
        return None


def ip(value):
    # Neighbor addresses are re-read for every IPAM row; parse each value once.
    try:
        return _ip(value)
    except TypeError:
        return _ip.__wrapped__(value)


@lru_cache(maxsize=65536)
def _mac(value):
    from .service import normalized_mac

    return normalized_mac(value)


def lldp_mac(value):
    try:
        return _mac(value)
    except TypeError:
        return _mac.__wrapped__(value)


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
    fdb_times = {}
    canonical_times = evidence.get("_canonical_fdb_times")
    required = {"vlan_fdb_port", "vlan_fdb_status", "vlan_fdb_id", "bridge_ifindex"}
    partial_positives = canonical_times is not None and all(
        name == "vlan_fdb_port"
        and evidence.get("table_reads", {}).get(name, {}).get("status") == "incomplete"
        and evidence.get("table_reads", {}).get(name, {}).get("error_code") == "unresolved_row_dependencies"
        for name in unsupported & required
    )
    if partial_positives or not unsupported.intersection(required):
        for index, bridge in tables.get("vlan_fdb_port", {}).items():
            try:
                fid, *octets = index.split(".")
                # RFC 4363 permits a learned port even with status other(1).
                # Invalid(2), self(4) and unknown/missing statuses prove no endpoint.
                if len(octets) != 6 or tables.get("vlan_fdb_status", {}).get(index) not in ("1", "3", "5"):
                    continue
                if not (1 <= (integer(bridge) or 0) <= 65535):
                    continue
                mac = bytes(int(v) for v in octets).hex(":")
                interface = interfaces.get(integer(tables.get("bridge_ifindex", {}).get(str(bridge))))
                if not interface or interface.get("oper_status") != "up" or not interface.get("name"):
                    continue
                population[interface["name"]].add(mac)
                # Shared filtering databases cannot establish a unique VLAN.
                if len(fids[fid]) == 1:
                    vid = next(iter(fids[fid]))
                elif not fids[fid] and (vid := evidence.get("_explicit_fdb_vlans", {}).get(index)):
                    pass
                else:
                    continue
                fdb[(vid, mac)].add(interface["name"])
                if canonical_times is not None:
                    fdb_times[(vid, mac, interface["name"])] = canonical_times.get(index)
            except (ValueError, TypeError):
                continue
    addresses = defaultdict(list)
    for address, mac, index in evidence.get("_bindings", bindings(tables, unsupported)):
        addresses[address].append((mac, index))
    return {
        "bindings": addresses,
        "fdb": fdb,
        "fdb_times": fdb_times,
        "population": population,
        "tables": tables,
        "unsupported": unsupported,
        "interfaces": interfaces,
        "names": {p.get("name") for p in interfaces.values()},
        "up": {p.get("name") for p in interfaces.values() if p.get("oper_status") == "up"},
        "down": {p.get("name") for p in interfaces.values() if p.get("oper_status") == "down"},
        "evidence": evidence,
    }


def gateway_interfaces(tables, network):
    attached = set()
    for item in tables.get("_prefixes", []):
        subnet = ipaddress.ip_network((item["address"], item["prefix_length"]), strict=False)
        if subnet.version == network.version and subnet.prefixlen and network.subnet_of(subnet):
            attached.add(item["if_index"])
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


Snapshot = namedtuple("Snapshot", "id created_at")


def projections(db, rows, *, model=m.Observation):
    """Transient SQL projection; source dictionaries are never kept as a second cache."""
    ids = [row.id for row in rows]
    found = {}
    for start in range(0, len(ids), 50):
        for row in db.scalars(select(model).where(model.id.in_(ids[start : start + 50]))):
            found[row.id] = project(row.evidence or {})
    return [(row, found[row.id]) for row in rows if row.id in found]


class Evidence:
    def for_address(self, db, row, observations):
        # All readers now share the canonical typed facts. There is no second
        # per-IP protocol payload to overlay on the same source record.
        return self

    def __init__(self, db, vrfs, *, source_devices=None):
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
        self.attached = {}
        self.static = {}
        self.raw_neighbors = {}
        self.excluded_raw_neighbors = {}
        self.exclusions = defaultdict(list)
        if not self.devices:
            self.links = []
            return
        # A newer empty/failed snapshot supersedes old positive evidence. Pick
        # latest before checking age/content so stale locations cannot reappear.
        from types import SimpleNamespace

        source_ids = (
            set(self.devices) if source_devices is None else set(source_devices) & self.devices.keys()
        )
        self.state_rows = list(
            db.scalars(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id.in_(source_ids)))
        )
        states = [
            SimpleNamespace(
                id=s.id,
                device_id=s.device_id,
                address=s.address,
                created_at=s.observed_at,
                updated_at=s.updated_at,
            )
            for s in self.state_rows
        ]
        from .network import read_context

        profile_ids = {
            id for d in self.devices.values() for id in (d.snmp_credential_id, d.config_credential_id) if id
        }
        profiles = (
            {
                p.id: p
                for p in db.scalars(
                    select(m.Credential)
                    .options(load_only(m.Credential.id, m.Credential.updated_at, m.Credential.protocol))
                    .where(m.Credential.id.in_(profile_ids))
                )
            }
            if states
            else {}
        )
        for row, projected in projections(db, states, model=m.IPAMNetworkState):
            if row.address != self.devices[row.device_id].management_ip:
                continue
            device = self.devices[row.device_id]
            profile = profiles.get(device.snmp_credential_id)
            ssh = (
                profiles.get(device.config_credential_id)
                if device.adapter in {"aruba_5400", "aruba_2900"}
                or (
                    device.adapter == "aruba_6100"
                    and (projected["evidence"].get("read_context") or [None] * 10)[8]
                )
                else None
            )
            if ssh and ssh.protocol != "ssh":
                ssh = None
            if not profile or projected["evidence"].get("read_context") != read_context(device, profile, ssh):
                self.snapshots.pop(row.device_id, None)
                continue
            previous = self.snapshots.get(row.device_id)
            if not previous or row.created_at > previous[0].created_at:
                self.snapshots[row.device_id] = (Snapshot(row.id, row.created_at), projected)
        self.links = list(
            db.scalars(
                select(m.Link).where(
                    m.Link.device_id.in_(source_ids),
                    m.Link.is_current.is_(True),
                    m.Link.auto_add_excluded.is_(False),
                    inventory_links(),
                )
            )
        )

        for link in db.scalars(
            select(m.Link).where(m.Link.device_id.in_(source_ids), m.Link.auto_add_excluded.is_(True))
        ):
            self.exclusions[(link.device_id, link.interface_name)].append(link)
        # Evidence is used after the collection session closes. Resolve the
        # scalar STP relationship while the canonical states are attached.
        for link in [*self.links, *(l for rows in self.exclusions.values() for l in rows)]:
            if link.local_port:
                _ = link.local_port.state
        self.refresh_neighbors()

    def refresh_neighbors(self):
        from ..discovery.link_deletions import matches as excluded_match

        for id, (obs, projected) in self.snapshots.items():
            accepted = []
            excluded_rows = []
            for raw in projected["evidence"].get("neighbors", []):
                neighbor = {"remote_name": "", "remote_port": "", "source": "lldp", **raw}
                port = neighbor.get("interface_name")
                if not port:
                    continue
                excluded = self.exclusions[(id, port)]
                if any(excluded_match(link, neighbor) for link in excluded):
                    excluded_rows.append(neighbor)
                    continue
                accepted.append(neighbor)
            self.raw_neighbors[id] = accepted
            self.excluded_raw_neighbors[id] = excluded_rows

    def _static_links(self, vrf_id, cutoff):
        """Row-independent links, blockers and lookup indexes for one VRF/window."""
        key = (vrf_id, cutoff)
        if key in self.static:
            return self.static[key]
        snapshots = {
            id: (o, p)
            for id, (o, p) in self.snapshots.items()
            if o.created_at >= cutoff
            and self.devices[id].vrf_id == vrf_id
            and not p["evidence"].get("failed")
        }
        links = []
        for i, link in enumerate(self.links):
            current = self.snapshots.get(link.device_id)
            if current and current[1]["evidence"].get("failed"):
                continue
            if (
                self.devices[link.device_id].vrf_id != vrf_id
                or not link.last_seen_at
                or link.last_seen_at < cutoff
            ):
                continue
            snapshot = snapshots.get(link.device_id)
            if snapshot and snapshot[0].created_at >= link.last_seen_at:
                data = snapshot[1]["evidence"]
                complete = set(data.get("neighbor_protocols_complete") or [])
                if data.get("failed"):
                    continue
                if set(link.source.split("+")) <= complete:
                    from ..discovery.links import legacy_match

                    if not any(legacy_match(link, n) for n in self.raw_neighbors.get(link.device_id, [])):
                        continue
            links.append(
                (
                    (0, i, 0, 0),
                    (
                        link.device_id,
                        link.interface_name,
                        link.remote_device_id,
                        link.evidence or {},
                        link.last_seen_at,
                        link.id,
                    ),
                )
            )
        for s, (id, (obs, p)) in enumerate(snapshots.items()):
            if p["evidence"].get("failed"):
                continue
            for j, neighbor in enumerate(self.raw_neighbors.get(id, [])):
                when = (
                    datetime.fromisoformat(neighbor["observed_at"])
                    if neighbor.get("observed_at")
                    else obs.created_at
                )
                if when < cutoff:
                    continue
                port = neighbor["interface_name"]
                if port in p["up"]:
                    links.append(
                        (
                            (1, s, 0, j),
                            (id, port, None, neighbor.get("evidence") or {}, when, obs.id),
                        )
                    )
        blocked = set()
        for id, (_, p) in snapshots.items():
            for n in p["evidence"].get("neighbors", []):
                for port in (
                    n.get("interface_name"),
                    (n.get("evidence", {}).get("local_aggregate") or {}).get("name"),
                ):
                    if port:
                        blocked.add((id, port))
        # Directory uplinks remain conservative blockers even if their direct
        # identity was superseded by a newer snapshot.
        for link in self.links:
            if link.last_seen_at and link.last_seen_at >= cutoff:
                blocked.add((link.device_id, link.interface_name))
        records, by_address, by_mac, by_uuid = [], defaultdict(list), defaultdict(list), defaultdict(list)
        for order, link in links:
            record = self._link_record(order, link, snapshots)
            if not record:
                continue
            blocked.update(record["blocks"])
            records.append(record)
            if record["down"]:
                continue
            index = len(records) - 1
            for address in record["addresses"]:
                by_address[address].append(index)
            for value in record["macs"]:
                by_mac[value].append(index)
            if record["uuid"]:
                by_uuid[record["uuid"]].append(index)
        self.static[key] = {
            "snapshots": snapshots,
            "records": records,
            "blocked": blocked,
            "by_address": by_address,
            "by_mac": by_mac,
            "by_uuid": by_uuid,
        }
        return self.static[key]

    def _link_record(self, order, link, snapshots):
        id, port, _remote, data, when, _proof_id = link
        if not port:
            return None
        aggregate = (data.get("local_aggregate") or {}).get("name")
        lldp = data.get("lldp") or {}
        chassis_mac = lldp_mac(lldp.get("chassis_id")) if lldp.get("chassis_subtype") == 4 else ""
        advertised = {chassis_mac, lldp_mac(lldp.get("port_id")) if lldp.get("port_subtype") == 3 else ""} - {
            ""
        }
        uuid = None
        try:
            if lldp.get("chassis_subtype") == 7:
                uuid = str(UUID(lldp.get("chassis_id", "")))
        except (ValueError, TypeError, AttributeError):
            pass
        snapshot = snapshots.get(id)
        return {
            "order": order,
            "link": link,
            "aggregate": aggregate,
            "blocks": {(id, p) for p in (port, aggregate) if p},
            "advertised": advertised,
            "chassis_mac": chassis_mac or None,
            "macs": advertised | ({chassis_mac} if chassis_mac else set()),
            "uuid": uuid,
            "addresses": {
                address
                for protocol in ("lldp", "cdp")
                if (address := ip((data.get(protocol) or {}).get("management_address")))
            },
            "down": bool(snapshot and snapshot[0].created_at >= when and port in snapshot[1]["down"]),
        }

    def _candidate(self, record, nic, peer, uuid, host):
        id, port, _, _, when, proof_id = record["link"]
        return {
            "device_id": id,
            "device_name": self.devices[id].name,
            "port": port,
            "aggregate": record["aggregate"],
            "source": "vcenter_host+neighbors" if nic else "ipam_ssh_neighbors" if peer else "neighbors",
            "observed_at": when.isoformat(),
            "evidence_id": proof_id,
            "endpoint_identity": host["identity"] if nic else peer["identity"] if peer else uuid,
            "nic": nic["device"] if nic else peer["nic"] if peer else "",
            "mac_address": nic["mac_address"] if nic else peer["mac_address"] if peer else "",
            "confidence": 0.95,
        }

    def resolve(self, row, vlan, *, identity_mac=None, identity_source="gateway", host=None):
        from .protocol_peers import peer as protocol_peer
        from .vmware_hosts import nic_for_neighbor

        lifetime = timedelta(seconds=max(300, min(vlan.discovery_interval * 2, 86400)))
        cutoff = self.at - lifetime
        static = self._static_links(row.vrf_id, cutoff)
        snapshots = static["snapshots"]
        network = ipaddress.ip_network(vlan.cidr)
        gateway = []
        for id, (obs, p) in snapshots.items():
            device = self.devices[id]
            # The address must be on a directly attached gateway interface.
            # A management host's ARP cache is not a gateway source.
            if (
                not device.is_gateway
                and device.kind not in ("router", "firewall")
                and str(p["evidence"].get("ip_forwarding")) != "1"
            ):
                continue
            if (id, network) not in self.attached:
                self.attached[(id, network)] = gateway_interfaces(p["tables"], network)
            attached = self.attached[(id, network)]

            gateway_at = p["evidence"].get("gateway_at")
            gateway_at = datetime.fromisoformat(gateway_at) if gateway_at else obs.created_at
            if gateway_at < cutoff:
                continue
            for mac, index in p["bindings"].get(row.address, ()):
                if index in attached:
                    gateway.append(
                        {
                            "device_id": id,
                            "device_name": device.name,
                            "mac_address": mac,
                            "source": "gateway",
                            "observed_at": gateway_at.isoformat(),
                        }
                    )
        gateway_macs = {g["mac_address"] for g in gateway}
        macs = {identity_mac} if identity_mac else gateway_macs
        records = static["records"]
        blocked = static["blocked"]
        extra = []
        for s, (id, (obs, p)) in enumerate(snapshots.items()):
            if p["evidence"].get("failed"):
                continue
            excluded = self.excluded_raw_neighbors.get(id, [])
            raw = [(0, n) for n in excluded if protocol_peer(n.get("evidence") or {}, row.address)]
            if host:
                # Fresh protocol evidence plus authenticated VMware NIC ownership
                # is independent of historical directory visibility. No link is restored.
                raw += [(1, n) for n in excluded if nic_for_neighbor(host, n.get("evidence") or {})]
            for j, (part, neighbor) in enumerate(raw):
                when = (
                    datetime.fromisoformat(neighbor["observed_at"])
                    if neighbor.get("observed_at")
                    else obs.created_at
                )
                if when < cutoff:
                    continue
                port = neighbor["interface_name"]
                if port in p["up"]:
                    link = (id, port, None, neighbor.get("evidence") or {}, when, obs.id)
                    record = self._link_record((1, s, 1 + part, j), link, snapshots)
                    if record:
                        extra.append(record)
        if extra:
            blocked = set(blocked)
            for record in extra:
                blocked.update(record["blocks"])
        if host:
            # Any typed NIC/chassis can match a VMware host: evaluate every link.
            relevant = [r for r in records if not r["down"]]
        else:
            # Without a host only an advertised address or MAC can make a link
            # direct; other links matter solely as members of a proven identity.
            indexes = set(static["by_address"].get(row.address, ()))
            for value in macs:
                indexes.update(static["by_mac"].get(value, ()))
            relevant = [records[i] for i in indexes]
        relevant += [r for r in extra if not r["down"]]
        relevant.sort(key=lambda r: r["order"])
        seen = {r["order"] for r in relevant}
        candidates = {}
        identities = defaultdict(list)
        direct = []
        identity_conflict = False
        conflicting_identities = []
        for record in relevant:
            _, _, remote, data, _, _ = record["link"]
            advertised = record["advertised"]
            nic = nic_for_neighbor(host, data)
            peer = protocol_peer(data, row.address)
            address_match = row.address in record["addresses"]
            uuid = record["uuid"]
            if not uuid and record["chassis_mac"] and record["chassis_mac"] in macs:
                uuid = "lldp-mac:" + record["chassis_mac"]
            candidate = self._candidate(record, nic, peer, uuid, host)
            if candidate["endpoint_identity"]:
                identities[candidate["endpoint_identity"]].append((record["order"], candidate))
            if nic or peer or address_match or (len(macs) == 1 and advertised & macs):
                if (
                    not nic
                    and not peer
                    and address_match
                    and len(macs) == 1
                    and advertised
                    and not advertised & macs
                ):
                    conflicting_identities.append(candidate["endpoint_identity"])
                    continue
                # A known infrastructure peer is transit unless its advertised IP
                # is the requested IP itself.
                if remote not in self.devices or address_match:
                    direct.append(candidate)
        # Links outside the row's address/MAC indexes are never direct, but a
        # typed chassis UUID still groups them with a proven candidate.
        for key in {c["endpoint_identity"] for c in direct} - {None}:
            for i in static["by_uuid"].get(key, ()):
                record = records[i]
                if record["order"] not in seen:
                    identities[key].append((record["order"], self._candidate(record, None, None, key, host)))
        identities = defaultdict(
            list, {k: [c for _, c in sorted(v, key=lambda x: x[0])] for k, v in identities.items()}
        )
        proven_identities = {c["endpoint_identity"] for c in direct} - {None}
        identity_conflict = any(not key or key not in proven_identities for key in conflicting_identities)
        if host:
            from .host_links import hint_candidates

            for candidate in hint_candidates(self, host, row, snapshots):
                direct.append(candidate)
                identities[host["identity"]].append(candidate)
        for candidate in direct:
            group = (
                identities[candidate["endpoint_identity"]] if candidate["endpoint_identity"] else [candidate]
            )
            for c in group:
                candidates[(c["device_id"], c["port"])] = c
        if not direct and len(macs) == 1:
            mac = next(iter(macs))
            roots = {id for id, d in self.devices.items() if d.vrf_id == row.vrf_id and backbone(d)}
            if roots:
                for (id, port), (obs, observed) in routed_ports(roots, static, vlan.vid, mac, cutoff).items():
                    candidates[(id, port)] = {
                        "device_id": id,
                        "device_name": self.devices[id].name,
                        "port": port,
                        "aggregate": None,
                        "source": identity_source + "+vlan_fdb",
                        "observed_at": observed,
                        "evidence_id": obs.id,
                        "endpoint_identity": None,
                        "confidence": 0.85,
                    }
            else:
                for id, (obs, p) in snapshots.items():
                    fdb_at = p["evidence"].get("fdb_at")
                    if (
                        "_canonical_fdb_times" not in p["evidence"]
                        and fdb_at
                        and datetime.fromisoformat(fdb_at) < cutoff
                    ):
                        continue
                    if not p["evidence"].get("neighbor_protocols_complete"):
                        continue
                    if any(
                        n.get("interface_name") not in p["names"] for n in p["evidence"].get("neighbors", [])
                    ):
                        # An unresolved LLDP local port could be the FDB uplink.
                        # Do not infer an edge until every advertised port is mapped.
                        continue
                    for port in p["fdb"].get((vlan.vid, mac), ()):
                        row_at = p["fdb_times"].get((vlan.vid, mac, port))
                        if "_canonical_fdb_times" in p["evidence"] and (
                            not row_at or datetime.fromisoformat(row_at) < cutoff
                        ):
                            continue
                        # Multi-MAC ports may hide another bridge, phone or hypervisor.
                        # They are not evidence of a direct endpoint attachment.
                        if (id, port) in blocked or p["population"].get(port) != {mac}:
                            continue
                        candidates[(id, port)] = {
                            "device_id": id,
                            "device_name": self.devices[id].name,
                            "port": port,
                            "aggregate": None,
                            "source": identity_source + "+vlan_fdb",
                            "observed_at": row_at or obs.created_at.isoformat(),
                            "evidence_id": obs.id,
                            "endpoint_identity": None,
                            "confidence": 0.85,
                        }
        values = sorted(candidates.values(), key=lambda c: (c["device_name"], c["port"]))
        identities = {c["endpoint_identity"] for c in values}
        aggregates = {(c["device_id"], c["aggregate"]) for c in values}
        nic_locations = defaultdict(set)
        for candidate in values:
            if candidate.get("nic"):
                nic_locations[candidate["nic"]].add((candidate["device_id"], candidate["port"]))
        nic_conflict = any(len(ports) > 1 for ports in nic_locations.values())
        grouped = len(values) > 1 and (
            (len(identities) == 1 and None not in identities)
            or (len(aggregates) == 1 and values[0]["aggregate"])
        )
        ambiguous = nic_conflict or identity_conflict or len(macs) > 1 or (len(values) > 1 and not grouped)
        accepted = values if not ambiguous else []
        groups = {}
        for c in accepted:
            group = groups.setdefault(
                c["device_id"], {"device_id": c["device_id"], "device_name": c["device_name"], "ports": []}
            )
            group["ports"].append(c["port"])
        for g in groups.values():
            g["port_label"] = (" - " if host else " / ").join(g["ports"])
        reason = (
            "Çelişkili gateway MAC kayıtları"
            if len(macs) > 1
            else "Aynı VMware NIC için birden fazla fiziksel port kanıtı"
            if nic_conflict
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
            "gateway_mac_conflict": len(gateway_macs) > 1,
            "gateway_evidence": gateway,
            "connections": values,
            "connection_groups": list(groups.values()),
            "connected_device": " / ".join(g["device_name"] for g in groups.values()),
            "connected_port": " / ".join(g["port_label"] for g in groups.values()),
            "connection_type": "physical" if accepted else "",
            "connection_ambiguous": bool(ambiguous),
            "connection_reason": reason,
        }
