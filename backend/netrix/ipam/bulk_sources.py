"""Scheduled source snapshots read once, resolve each IP using the same branching rules."""

import asyncio
import copy
import ipaddress
import json
from collections import defaultdict
from types import SimpleNamespace

from .. import models as m
from ..core import now, session_factory
from ..discovery.protocols import NetworkError
from ..identity.security import decrypt
from ..runtime_limits import sql_read
from . import adapters
from .connections import Evidence
from .gateway_sources import binding_view, bindings_query
from .point_sources import PointSources, integration_signature
from .service import normalized_mac


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
        self.gateway_bindings = {}
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

                self.switch_evidence = self.gateway_evidence = await sql_read(load_inventory)
                self.values[kind] = True
                return

            def load_gateway():
                network = ipaddress.ip_network(self.base.vlan.cidr)
                matches = defaultdict(list)
                with session_factory()() as db:
                    for binding in db.scalars(bindings_query(self.base.vlan.vrf_id, self.base.devices)):
                        if ipaddress.ip_address(binding.address) in network:
                            matches[binding.address].append(
                                (
                                    binding_view(binding, self.base.devices[binding.device_id]),
                                    {
                                        "kind": "gateway",
                                        "id": binding.id,
                                        "source_key": binding.source_key,
                                        "observed_at": binding.observed_at.isoformat(),
                                    },
                                )
                            )
                return matches

            self.gateway_bindings = await sql_read(load_gateway)
            self.values[kind] = True

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
    gateway_sql = True

    def __init__(self, point, context):
        self.point, self.context = point, context
        self.dns_source_key = point.vlan.dns_server_id or "system"

    async def gateway(self, address):
        c = self.context
        await c.network("gateway")
        entries = c.gateway_bindings.get(address, [])
        matches = [value for value, _ in entries]
        macs = {r["mac_address"] for r in matches}
        if len(macs) > 1:
            raise NetworkError("Conflicting gateway identities")
        return {
            "mac_address": next(iter(macs)) if macs else "",
            "gateway_evidence": matches,
            "refs": [ref for _, ref in entries],
        }

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
