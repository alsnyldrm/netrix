"""Gateway/integration sources; switch attachments are read only from inventory SQL."""

import asyncio
import ipaddress
import json

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..discovery.protocols import NetworkError
from ..identity.security import decrypt, secret_data
from . import adapters
from .connections import Evidence, gateway_interfaces
from .network import detail_profile
from .service import normalized_mac


def integration_signature(config):
    return tuple(
        getattr(config, key) for key in ("kind", "host", "port", "enabled", "verify_tls", "encrypted_secret")
    )


class PointSources:
    def __init__(self, db, row, vlan, collector):
        self.row, self.vlan, self.collector = row, vlan, collector
        self.dns_source_key = vlan.dns_server_id or "system"
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
        from .mac_cache import is_switch

        devices = [
            id
            for id, d in self.devices.items()
            if (d.is_gateway or d.kind in ("router", "firewall")) and not is_switch(d)
        ]
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
        """Resolve existing inventory facts; a missing match never opens a switch session."""
        from .inventory_sources import attachment

        self.check()
        with session_factory()() as db:
            return attachment(db, self.row, self.vlan, mac, evidence=self.evidence)
