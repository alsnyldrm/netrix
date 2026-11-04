"""One-address source plan. Topology/cache are routing hints, not live whole-network reads."""

import asyncio
import ipaddress
import json

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..discovery.protocols import NetworkError, fetch_neighbor_ports
from ..identity.security import decrypt, secret_data
from . import adapters
from .connections import Evidence, Snapshot, gateway_interfaces, lldp_mac, projections
from .network import detail_profile
from .protocol_peers import peer
from .service import normalized_mac


def integration_signature(config):
    return tuple(
        getattr(config, key) for key in ("kind", "host", "port", "enabled", "verify_tls", "encrypted_secret")
    )


class PointSources:
    def __init__(self, db, row, vlan, collector):
        self.row, self.vlan, self.collector = row, vlan, collector
        self.evidence = Evidence(db, {row.vrf_id})
        self.devices = {
            id: d
            for id, d in self.evidence.devices.items()
            if d.lifecycle_status == "active" and d.snmp_credential_id
        }
        self.profiles = {id: db.get(m.Credential, d.snmp_credential_id) for id, d in self.devices.items()}
        self.ssh = {id: detail_profile(db, d) for id, d in self.devices.items()}
        self.configs = list(db.scalars(select(m.Integration).where(m.Integration.enabled.is_(True))))
        self.dns_server = db.get(m.DNSServer, vlan.dns_server_id) if vlan.dns_server_id else None
        self.hints = {}
        for o in db.scalars(
            select(m.IPObservation).where(
                m.IPObservation.address_id == row.id, m.IPObservation.source == "vcenter"
            )
        ):
            if o.data.get("vm_id") and o.data.get("present", True):
                self.hints.setdefault(o.data.get("integration_id"), []).append(o.data["vm_id"])
        previous = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == row.id))
        if previous:
            for entry in previous.values.get("vm_ids", []):
                if entry.get("vm_id"):
                    self.hints.setdefault(entry.get("integration_id"), []).append(entry["vm_id"])
        self.used_configs = {}

    def check(self):
        from ..worker import Cancelled

        with session_factory()() as db:
            job = db.get(m.Job, getattr(self, "job_id", None)) if getattr(self, "job_id", None) else None
            if job and job.cancel_requested:
                raise Cancelled()
            for id, expected in self.used_configs.items():
                config = db.get(m.Integration, id)
                if not config or integration_signature(config) != expected:
                    raise Cancelled()
            current = db.get(m.IPAddress, self.row.id)
            vlan = db.get(m.VLAN, self.vlan.id)
            if (
                not current
                or current.nic_teaming
                or not vlan
                or [current.address, current.vrf_id, current.vlan_id]
                != [self.row.address, self.row.vrf_id, self.vlan.id]
                or vlan.cidr != self.vlan.cidr
                or vlan.dns_server_id != self.vlan.dns_server_id
            ):
                raise Cancelled()

    def config_check(self, config):
        from ..worker import Cancelled

        with session_factory()() as db:
            current = db.get(m.Integration, config.id)
            if not current or integration_signature(current) != integration_signature(config):
                raise Cancelled()
        self.used_configs[config.id] = integration_signature(config)

    def device_check(self, id):
        from ..worker import Cancelled

        with session_factory()() as db:
            current = db.get(m.Device, id)
            profile = db.get(m.Credential, self.profiles[id].id)
            d = self.devices[id]
            ssh = self.ssh[id]
            current_ssh = db.get(m.Credential, ssh.id) if ssh else None
            if ssh and (not current_ssh or current_ssh.updated_at != ssh.updated_at):
                raise Cancelled()
            if (
                not current
                or current.archived
                or current.lifecycle_status != "active"
                or not current.discovery_scope_id
                or not profile
                or profile.updated_at != self.profiles[id].updated_at
                or (
                    current.management_ip,
                    current.vrf_id,
                    current.snmp_credential_id,
                    current.adapter,
                    current.config_port,
                    current.config_credential_id,
                    current.ssh_trust_host_key,
                )
                != (
                    d.management_ip,
                    d.vrf_id,
                    d.snmp_credential_id,
                    d.adapter,
                    d.config_port,
                    d.config_credential_id,
                    d.ssh_trust_host_key,
                )
            ):
                raise Cancelled()

    async def gateway(self, address):
        matches, errors = [], []
        devices = [id for id, d in self.devices.items() if d.is_gateway or d.kind in ("router", "firewall")]
        if not devices:
            raise NetworkError("No authorized gateway configured")
        known, unknown = [], []
        for id in devices:
            hint = self.evidence.snapshots.get(id)
            if not hint:
                unknown.append(id)
            elif gateway_interfaces(hint[1]["tables"], ipaddress.ip_network(self.vlan.cidr)):
                known.append(id)
        devices = known or unknown
        if len(devices) > 4:
            raise NetworkError("Ambiguous gateway source plan")
        for id in devices:
            self.check()
            self.device_check(id)
            d = self.devices[id]
            hint = self.evidence.snapshots.get(id)
            indexes = (
                gateway_interfaces(hint[1]["tables"], ipaddress.ip_network(self.vlan.cidr)) if hint else set()
            )
            # A gateway without this subnet is not an identity source.
            if hint and not indexes:
                continue
            try:
                async with asyncio.timeout(10):
                    macs = await self.collector.ipam_gateway(
                        d.management_ip,
                        d.snmp_port,
                        secret_data(self.profiles[id]),
                        address,
                        {"indexes": sorted(indexes), "network": self.vlan.cidr},
                    )
                self.device_check(id)
                from ..sources.point import gateway as store_gateway

                with session_factory()() as db:
                    store_gateway(db, self.row, d, macs)
                    db.commit()
                matches.extend(
                    {
                        "device_id": id,
                        "device_name": d.name,
                        "mac_address": mac,
                        "source": "gateway",
                        "observed_at": now().isoformat(),
                    }
                    for mac in macs
                )
            except (NetworkError, TimeoutError, OSError) as exc:
                errors.append(
                    {
                        "source": "gateway",
                        "code": type(exc).__name__,
                        "message": f"{d.name}: gateway IP/MAC sorgusu okunamadı ({type(exc).__name__}).",
                    }
                )
        macs = {g["mac_address"] for g in matches}
        if len(macs) > 1:
            raise NetworkError("Conflicting gateway identities")

        self.gateway_result = {
            "mac_address": next(iter(macs)) if macs else "",
            "gateway_evidence": matches,
            "issues": errors,
        }
        return self.gateway_result

    async def integration(self, kind, reader, *args):
        rows = []
        for config in self.configs:
            if config.kind != kind:
                continue
            self.check()
            self.config_check(config)
            async with asyncio.timeout(25):
                records = await asyncio.to_thread(
                    reader, config, json.loads(decrypt(config.encrypted_secret)), *args
                )
            from ..worker import Cancelled

            with session_factory()() as db:
                current = db.get(m.Integration, config.id)
                if (
                    not current
                    or not current.enabled
                    or integration_signature(current) != integration_signature(config)
                ):
                    raise Cancelled()
            from ..sources.records import save_integration

            with session_factory()() as db:
                save_integration(db, config, records)
                db.commit()
            rows.extend({**r, "integration_id": config.id} for r in records)
        return rows

    async def vmware(self, address, mac):
        rows = []
        for config in self.configs:
            if config.kind != "vcenter":
                continue
            self.check()
            self.config_check(config)
            async with asyncio.timeout(25):
                values = await asyncio.to_thread(
                    adapters.vcenter_point,
                    config,
                    json.loads(decrypt(config.encrypted_secret)),
                    address,
                    mac,
                    self.hints.get(config.id, ()),
                )
            from ..worker import Cancelled

            with session_factory()() as db:
                current = db.get(m.Integration, config.id)
                if (
                    not current
                    or not current.enabled
                    or integration_signature(current) != integration_signature(config)
                ):
                    raise Cancelled()
            from ..sources.records import save_integration

            with session_factory()() as db:
                save_integration(db, config, values)
                db.commit()
            rows.extend({**r, "integration_id": config.id} for r in values)
        return self.host_records(rows)

    def host_records(self, records):
        for record in records:
            for nic in record.get("physical_nics", []):
                for hint in nic.get("hints", []):
                    matches = [
                        d
                        for d in self.devices.values()
                        if d.management_ip in hint.get("addresses", [])
                        or d.name.casefold() == str(hint.get("chassis_id", "")).casefold()
                    ]
                    if len(matches) == 1:
                        hint.update(chassis_id=matches[0].name, device_id=matches[0].id)
                    elif normalized_mac(hint.get("chassis_id")):
                        hint["chassis_id"] = ""
        return records

    async def dhcp(self, address, mac):
        return await self.integration("windows_dhcp", adapters.windows_dhcp_point, address, mac)

    async def dns(self, address):
        self.check()
        return await adapters.reverse_dns(address, self.dns_server)

    async def physical(self, address, mac):
        # Query only roots and downstream devices indicated by cached topology/FDB.
        cached = self.evidence.resolve(self.row, self.vlan, identity_mac=mac)
        if not cached["connections"] and not cached["connection_ambiguous"]:
            from .mac_cache import fallback

            gateway = getattr(self, "gateway_result", {"gateway_evidence": []})
            probe = {**cached, "gateway_evidence": gateway["gateway_evidence"], "sources": []}
            with session_factory()() as db:
                cached = fallback(db, [self.row], [probe], {self.vlan.id: self.vlan}, self.evidence)[0]
                source_ids = {c["device_id"] for c in cached["connections"]}
                states = list(
                    db.scalars(
                        select(m.SwitchMacSnapshot).where(m.SwitchMacSnapshot.device_id.in_(source_ids))
                    )
                )
                for state, projected in projections(db, states, model=m.SwitchMacSnapshot):
                    if state.device_id not in self.evidence.snapshots:
                        self.evidence.snapshots[state.device_id] = (
                            Snapshot(state.id, state.observed_at),
                            projected,
                        )
        roots = [
            id
            for id, d in self.devices.items()
            if not (d.is_gateway or d.kind in ("router", "firewall"))
            and (
                "backbone" in ((d.device_type.name if d.device_type else d.kind).casefold())
                or "-BB-" in d.name.upper()
            )
        ]
        if not roots:
            roots = list(dict.fromkeys([c["device_id"] for c in cached["connections"]]))
        if not roots:
            roots = [
                id
                for id, (_, p) in self.evidence.snapshots.items()
                if id in self.devices and p["fdb"].get((self.vlan.vid, mac))
            ]
        if len(roots) > 4:
            raise NetworkError("Ambiguous switch starting points")
        queue = list(roots)
        visited = set()
        connections = []
        steps = []
        while queue:
            id = queue.pop(0)
            if id in visited:
                continue
            if len(visited) >= 8:
                raise NetworkError("Switch path depth limit exceeded")
            visited.add(id)
            if id not in self.devices:
                continue
            self.check()
            self.device_check(id)
            d = self.devices[id]
            snapshot = self.evidence.snapshots.get(id)
            hint = snapshot[1]["evidence"] if snapshot else {}
            async with asyncio.timeout(10):
                data = await self.collector.ipam_switch(
                    d.management_ip, d.snmp_port, secret_data(self.profiles[id]), mac, self.vlan.vid, hint
                )
            self.device_check(id)
            steps.append(
                {
                    "source": "switch",
                    "device": d.name,
                    "status": "ok",
                    "ports": [p["port"] for p in data["ports"]],
                }
            )
            neighbors = data.get("neighbors", [])
            # Target-port SSH detail provides fresh IP/chassis, multiple NIC and LAG proof.
            if self.ssh[id] and data["ports"]:
                ports = {p["port"] for p in data["ports"]}
                members = {
                    c["port"]
                    for c in cached["connections"]
                    if c["device_id"] == id and c.get("aggregate") in ports
                }
                if members:
                    ports = members
                else:
                    ports.update(c["port"] for c in cached["connections"] if c["device_id"] == id)
                async with asyncio.timeout(10):
                    detail = await fetch_neighbor_ports(d, secret_data(self.ssh[id]), sorted(ports))
                from ..discovery.neighbor_detail import merge_neighbors

                neighbors = merge_neighbors(neighbors, detail.get("neighbors", []))
                for n in neighbors:
                    n["evidence"]["local_aggregate"] = detail.get("trunks", {}).get(n["interface_name"])
            from ..sources.point import switch as store_switch

            self.device_check(id)
            with session_factory()() as db:
                store_switch(db, d, self.vlan, mac, data["ports"], neighbors)
                db.commit()
            direct = []
            for n in neighbors:
                proof = peer(n.get("evidence") or {}, address)
                lldp = (n.get("evidence") or {}).get("lldp", {})
                identity = (
                    proof["identity"]
                    if proof
                    else ("mac:" + mac if lldp_mac(lldp.get("chassis_id")) == mac else None)
                )
                if identity:
                    direct.append(
                        {
                            "device_id": id,
                            "device_name": d.name,
                            "port": n["interface_name"],
                            "aggregate": ((n.get("evidence") or {}).get("local_aggregate") or {}).get("name"),
                            "source": "neighbors",
                            "endpoint_identity": identity,
                            "confidence": 0.95,
                            "observed_at": now().isoformat(),
                        }
                    )
            if direct:
                connections.extend(direct)
                continue
            for entry in data["ports"]:
                port = entry["port"]
                peers = [n for n in neighbors if n["interface_name"] == port]
                next_ids = set()
                for n in peers:
                    name = n.get("remote_name", "").casefold().rstrip(".")
                    next_ids.update(
                        rid
                        for rid, remote in self.devices.items()
                        if rid != id
                        and name
                        in {
                            remote.name.casefold().rstrip("."),
                            getattr(remote, "hostname", "").casefold().rstrip("."),
                        }
                    )
                next_ids.update(
                    l.remote_device_id
                    for l in self.evidence.links
                    if l.device_id == id and l.interface_name == port and l.remote_device_id in self.devices
                )
                if next_ids:
                    queue.extend(sorted(next_ids))
                    continue
                # Reconfirm the exact FDB row; single-MAC edge evidence must already exist.
                projected = snapshot[1] if snapshot else None
                if (
                    peers
                    or not projected
                    or not projected["evidence"].get("neighbor_protocols_complete")
                    or projected["population"].get(port) != {mac}
                ):
                    continue
                connections.append(
                    {
                        "device_id": id,
                        "device_name": d.name,
                        "port": port,
                        "aggregate": None,
                        "source": "gateway+vlan_fdb",
                        "endpoint_identity": None,
                        "confidence": 0.85,
                        "observed_at": now().isoformat(),
                    }
                )
        identities = {c.get("endpoint_identity") for c in connections}
        aggregate = {(c["device_id"], c.get("aggregate")) for c in connections}
        ambiguous = (
            len(connections) > 1
            and not (len(identities) == 1 and None not in identities)
            and not (len(aggregate) == 1 and connections[0].get("aggregate"))
        )
        return {"connections": connections, "connection_ambiguous": ambiguous, "steps": steps}
