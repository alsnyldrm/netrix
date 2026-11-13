"""Scheduled source snapshots read once, resolve each IP using the same branching rules."""

import asyncio
import copy
import ipaddress
import json
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from .. import models as m
from ..core import now, session_factory
from ..discovery.protocols import NetworkError
from ..identity.security import decrypt, secret_data
from ..runtime_limits import device_slot, sql_read, sql_write
from . import adapters
from .connections import Evidence, gateway_interfaces
from .mac_cache import is_switch
from .network import read_context
from .point_sources import PointSources, integration_signature
from .service import normalized_mac

# Matches the SNMP collector ceiling; a full gateway ARP read does not fit in a minute.
READ_BUDGET_SECONDS = 185


class BulkContext:
    def __init__(self, db, vlan, collector, job_id):
        self.job_id = job_id
        self.base = PointSources(
            db, SimpleNamespace(id="", vrf_id=vlan.vrf_id, address="", vlan_id=vlan.id), vlan, collector
        )
        self.values = {}
        self.indexes = {}
        self.errors = {}
        self.locks = {key: asyncio.Lock() for key in ("gateway", "switch", "vcenter", "windows_dhcp")}
        self.failed_devices = set()
        self.read_counts = {"gateway": 0, "switch": 0}
        self.gateway_evidence = None
        self.switch_evidence = None

    def check(self):
        from ..worker import Cancelled
        from .service import scan_boundary

        with session_factory()() as db:
            job = db.get(m.Job, self.job_id)
            vlan = db.get(m.VLAN, self.base.vlan.id)
            if (
                not job
                or job.cancel_requested
                or not vlan
                or vlan.cidr != self.base.vlan.cidr
                or vlan.vrf_id != self.base.vlan.vrf_id
                or vlan.dns_server_id != self.base.vlan.dns_server_id
            ):
                raise Cancelled()
            scan_boundary(db, vlan)
            for config in self.base.configs:
                if config.kind not in self.values:
                    continue
                current = db.get(m.Integration, config.id)
                if not current or integration_signature(current) != integration_signature(config):
                    raise Cancelled()

    async def network(self, kind):
        async with self.locks[kind]:
            if kind in self.values:
                return
            self.check()
            if kind == "switch":
                # Inventory is the only switch collector. IPAM reads its canonical
                # facts even when they are absent/incomplete; never probe a fallback.
                def load_inventory():
                    with session_factory()() as db:
                        return Evidence(db, {self.base.vlan.vrf_id})

                self.switch_evidence = await sql_read(load_inventory)
                self.values[kind] = True
                return
            ids = [
                id
                for id, d in self.base.devices.items()
                if (d.is_gateway or d.kind in ("router", "firewall")) and not is_switch(d)
            ]
            failures = []

            def save(id, d, data, profile, ssh):
                with session_factory()() as db:
                    item = db.scalar(
                        select(m.IPAMNetworkState)
                        .where(m.IPAMNetworkState.device_id == id)
                        .with_for_update(of=m.IPAMNetworkState)
                    )
                    if item is None:
                        item = m.IPAMNetworkState(device_id=id, address=d.management_ip)
                        db.add(item)
                    item.evidence = {**data, "read_context": read_context(d, profile, ssh)}
                    item.address, item.observed_at = d.management_ip, now()
                    db.commit()

            async def read(id):
                async with device_slot():
                    self.check()
                    self.read_counts[kind] += 1
                    self.base.device_check(id)
                    d = self.base.devices[id]
                    profile = self.base.profiles[id]
                    ssh = self.base.ssh[id]
                    try:
                        # Only non-switch gateway devices may be contacted by IPAM.
                        async with asyncio.timeout(READ_BUDGET_SECONDS):
                            data = await self.base.collector.ipam(
                                d.management_ip, d.snmp_port, secret_data(profile)
                            )
                    except Exception as exc:
                        from ..worker import Cancelled

                        if isinstance(exc, Cancelled):
                            raise
                        failures.append(type(exc).__name__)
                        self.failed_devices.add(id)
                        # Preserve the previous protocol snapshot on a transport error.
                        return
                self.check()
                self.base.device_check(id)
                try:
                    await sql_write(save, id, d, data, profile, ssh)
                except OperationalError as exc:
                    # One device's lost write is a failed source, not a failed VLAN scan.
                    failures.append(type(exc).__name__)
                    self.failed_devices.add(id)

            tasks = [asyncio.create_task(read(id)) for id in ids]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            self.values[kind] = True

            def load():
                with session_factory()() as db:
                    return Evidence(db, {self.base.vlan.vrf_id})

            evidence = await sql_read(load)
            evidence.snapshots = {
                id: state for id, state in evidence.snapshots.items() if id not in self.failed_devices
            }
            evidence.static = {}
            self.gateway_evidence = evidence
            if failures:
                self.errors[kind] = failures

    async def integration(self, kind):
        async with self.locks[kind]:
            if kind not in self.values:
                self.check()
                rows = []
                try:
                    for config in self.base.configs:
                        if config.kind != kind:
                            continue
                        secret = json.loads(decrypt(config.encrypted_secret))
                        async with asyncio.timeout(300):
                            values = (
                                await asyncio.to_thread(adapters.vcenter_records, config, secret)
                                if kind == "vcenter"
                                else await asyncio.to_thread(
                                    adapters.windows_dhcp, config, secret, preserve_conflicts=True
                                )
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

                            save_integration(db, current, values, complete=True)
                            current.last_run_at = current.last_success_at = now()
                            db.commit()
                        rows.extend({**r, "integration_id": config.id} for r in values)
                    self.values[kind] = rows
                except Exception as exc:
                    from ..worker import Cancelled

                    if isinstance(exc, Cancelled):
                        raise
                    self.values[kind] = []
                    self.errors[kind] = type(exc).__name__
            if kind in self.errors:
                raise NetworkError("Scheduled integration source failed")
            if kind not in self.indexes:
                by_ip, by_mac, owners = defaultdict(list), defaultdict(list), defaultdict(set)
                for record in self.values[kind]:
                    by_ip[record.get("address")].append(record)
                    mac = normalized_mac(record.get("mac_address"))
                    if mac:
                        by_mac[mac].append(record)
                        owners[mac].add(
                            (
                                record.get("integration_id"),
                                record.get("vm_id") or record.get("host_id"),
                                record.get("nic_key") or record.get("vmkernel_device"),
                            )
                        )
                self.indexes[kind] = (by_ip, by_mac, owners)
            return self.values[kind]

    def for_row(self, row):
        result = copy.copy(self.base)
        result.row = row
        return BulkSources(result, self)


class BulkSources:
    inventory_fallback = True

    def __init__(self, point, context):
        self.point, self.context = point, context
        self.dns_source_key = point.vlan.dns_server_id or "system"

    async def gateway(self, address):
        c = self.context
        await c.network("gateway")
        network = ipaddress.ip_network(self.point.vlan.cidr)
        matches = []
        for id, (snapshot, p) in c.gateway_evidence.snapshots.items():
            if id not in self.point.devices:
                continue
            d = self.point.devices[id]
            if not (d.is_gateway or d.kind in ("router", "firewall")):
                continue
            indexes = gateway_interfaces(p["tables"], network)
            matches.extend(
                {
                    "device_id": id,
                    "device_name": d.name,
                    "mac_address": mac,
                    "source": "gateway",
                    "observed_at": snapshot.created_at.isoformat(),
                }
                for mac, index in p["bindings"].get(address, [])
                if index in indexes
            )
        macs = {r["mac_address"] for r in matches}
        if len(macs) > 1:
            raise NetworkError("Conflicting gateway identities")
        if not macs and c.failed_devices:
            raise NetworkError("Scheduled gateway source failed")
        return {"mac_address": next(iter(macs)) if macs else "", "gateway_evidence": matches}

    async def vmware(self, address, mac):
        await self.context.integration("vcenter")
        by_ip, by_mac, owners = self.context.indexes["vcenter"]
        rows = list(by_ip.get(address, []))
        if mac and len(owners.get(mac, ())) == 1:
            rows.extend(r for r in by_mac.get(mac, []) if r.get("address") != address)
        return self.point.host_records([{**r, "point_match": True} for r in rows])

    async def physical(self, address, mac):
        await self.context.network("switch")
        from .inventory_sources import attachment

        with session_factory()() as db:
            return attachment(db, self.point.row, self.point.vlan, mac, evidence=self.context.switch_evidence)

    async def dhcp(self, address, mac):
        await self.context.integration("windows_dhcp")
        by_ip, by_mac, _ = self.context.indexes["windows_dhcp"]
        return list(by_ip.get(address, [])) + [r for r in by_mac.get(mac, []) if r.get("address") != address]

    async def dns(self, address):
        self.context.check()
        return await adapters.reverse_dns(address, self.point.dns_server)
