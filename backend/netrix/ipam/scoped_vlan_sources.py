"""Manual VLAN work uses only per-IP/MAC readers; shared source snapshots stay untouched."""

import asyncio
from copy import copy
from types import SimpleNamespace

from .. import models as m
from ..core import session_factory
from .point_sources import PointSources
from .service import scan_boundary


class ScopedVLANContext:
    def __init__(self, db, vlan, collector, job_id):
        self.job_id = job_id
        self.base = PointSources(
            db, SimpleNamespace(id="", address="", vrf_id=vlan.vrf_id, vlan_id=vlan.id), vlan, collector
        )
        self.semaphore = asyncio.Semaphore(4)
        self.errors = {}
        self.read_counts = {"gateway": 0}

    def check(self):
        from ..worker import Cancelled

        with session_factory()() as db:
            job = db.get(m.Job, self.job_id)
            vlan = db.get(m.VLAN, self.base.vlan.id)
            if (
                not job
                or job.cancel_requested
                or not vlan
                or job.target_id != vlan.id
                or job.kind != "ipam_discover"
                or job.result.get("ipam_origin") != "manual"
                or not job.requested_by
                or vlan.cidr != self.base.vlan.cidr
                or vlan.vrf_id != self.base.vlan.vrf_id
                or vlan.dns_server_id != self.base.vlan.dns_server_id
            ):
                raise Cancelled()
            scan_boundary(db, vlan)

    async def gateway(self, address):
        """Probe this in-scope address even if ICMP is silent and no IP row exists yet."""
        from ..services import in_scope
        from ..worker import Cancelled

        self.check()
        with session_factory()() as db:
            if not in_scope(address, scan_boundary(db, db.get(m.VLAN, self.base.vlan.id))):
                raise Cancelled()
        async with self.semaphore:
            self.check()
            probe = copy(self.base)
            # This probe can precede IP creation; the VLAN/job boundary owns admission.
            # All later source reads use PointSources' ordinary persisted-IP checks.
            probe.check = self.check
            self.read_counts["gateway"] += 1
            try:
                return await probe.gateway(address)
            except Cancelled:
                raise
            except Exception as exc:
                self.errors[address] = type(exc).__name__
                return exc

    def for_row(self, row, gateway):
        with session_factory()() as db:
            point = PointSources(db, row, self.base.vlan, self.base.collector)
        point.job_id = self.job_id
        point.gateway_result = gateway if isinstance(gateway, dict) else {"gateway_evidence": []}

        async def saved_gateway(address):
            point.check()
            if isinstance(gateway, Exception):
                raise gateway
            for proof in gateway.get("gateway_evidence", []):
                self.base.device_check(proof["device_id"])
            return gateway

        point.gateway = saved_gateway
        return point
