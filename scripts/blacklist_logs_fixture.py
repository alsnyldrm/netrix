"""ACL event UI fixture. Every record is local documentation-address test data."""

import os
from datetime import timedelta

from netrix import models as m
from netrix.blacklist import logs
from netrix.core import now, session_factory
from sqlalchemy import select

from scripts.blacklist_fixture import app  # noqa: F401

os.environ["NETRIX_ACL_LOG_HOST"] = "192.0.2.87"
logs.settings().acl_log_host = "192.0.2.87"
fixture_now = now()
logs.now = lambda: fixture_now

class MemoryRedis:
    def get(self, key):
        return fixture_now.isoformat() if key == "netrix:acl_logs:heartbeat" else None


logs.redis_client = lambda: MemoryRedis()
with session_factory()() as db:
    devices = list(db.scalars(select(m.Device).where(m.Device.is_gateway.is_(False)).order_by(m.Device.name)))
    for index in range(65):
        device = devices[index % len(devices)]
        stamp = fixture_now - timedelta(minutes=index, seconds=1)
        db.add(m.ACLLog(
            device_id=device.id, received_at=stamp, occurred_at=stamp - timedelta(seconds=1),
            peer_address=device.management_ip, transport="syslog_udp",
            acl="BLOCKED_IPS", source_address="192.0.2.200",
            destination_address="198.51.100.20", action="deny",
            message=f"ACL BLOCKED_IPS denied src=192.0.2.200 dst=198.51.100.20 fixture event {index}",
        ))
    db.commit()
