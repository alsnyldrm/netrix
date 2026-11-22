"""Device-originated ACL messages and logging plans, using local fixtures only."""

import asyncio
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.blacklist import adapters, logs
from netrix.blacklist.log_receiver import MAX_MESSAGE, Receiver, read_frame
from netrix.core import now
from sqlalchemy import func, select
from test_blacklist import create_group, group_payload
from test_blacklist import devices as devices
from test_blacklist_delivery import PROFILES, DeviceCLI, base_config

CX_LOG = b"<134>1 2026-11-22T10:11:12+03:00 switch ops-switchd 17 ACL - List BLOCK, seq# 10 denied icmp 192.0.2.100 -> 198.51.100.20 on port 1/1/1"
AOS_LOG = b"<134>Nov 22 10:11:12 switch ACL BLOCK denied src=192.0.2.100 dst=198.51.100.20"
CONTROLLER_LOG = b"<132>Nov 22 10:11:12 :124006: <WARN> |authmgr| {1} ICMP srcip=192.0.2.100 dstip=198.51.100.20, type=8, action=deny, role=logon, policy=BLOCK"
HP_LOG = b"<134>Nov 22 10:11:12 switch ACL/6/PFILTER: packet-filter ACL 3001 deny source=192.0.2.100 destination=198.51.100.20"


class LoggingCLI(DeviceCLI):
    async def command(self, command, **kwargs):
        if command.startswith("debug "):
            self.commands.append(command)
            return ""
        if command.startswith(("logging ", "info-center ", "acl logging ")):
            self.commands.append(command)
            self.config = self.config.replace("\nreturn\n", "\n") + command + "\n"
            if self.adapter == "hp_1950":
                self.config += "#\nreturn\n"
            return ""
        if command.startswith(("no ", "undo rule ")) and self.context:
            self.commands.append(command)
            sequence = command.split()[-1]
            parsed = dict(adapters.blocks(self.config))
            parsed[self.context] = [
                line for line in parsed[self.context]
                if not line.startswith((sequence + " ", "rule " + sequence + " "))
            ]
            self.config = base_config(self.adapter).replace("\nreturn\n", "\n") + "".join(
                header + "\n" + "".join(" " + line + "\n" for line in body)
                for header, body in parsed.items()
                if header not in {h for h, _ in adapters.blocks(base_config(self.adapter))}
            )
            if self.adapter == "hp_1950":
                self.config += "#\nreturn\n"
            return ""
        if command.endswith(" position 1"):
            self.commands.append(command)
            parsed = dict(adapters.blocks(self.config))
            parsed[self.context].insert(1, command.removesuffix(" position 1"))
            self.config = base_config(self.adapter) + "".join(
                header + "\n" + "".join(" " + line + "\n" for line in body)
                for header, body in parsed.items()
                if header not in {h for h, _ in adapters.blocks(base_config(self.adapter))}
            )
            return ""
        return await super().command(command, **kwargs)


@pytest.mark.parametrize("adapter,profile", PROFILES)
async def test_logging_upgrades_old_acl_without_removing_deny_first(adapter, profile):
    cli = LoggingCLI(adapter)
    initial = adapters.build_plan(adapter, profile, "192.0.2.100", cli.config, cli.ports)
    for command in initial.commands:
        await cli.command(command)
    upgraded = adapters.build_plan(adapter, profile, "192.0.2.101", cli.config, cli.ports,
        log_host="192.0.2.87", log_port=5514)
    for command in upgraded.commands:
        await cli.command(command)
        if command.startswith(("no ", "undo rule ")):
            # At every removal point a logged deny for the original IP already exists.
            assert "192.0.2.100" in cli.config
            assert " log" in cli.config
    adapters.verify(upgraded, cli.config, cli.ports)
    repeated = adapters.build_plan(adapter, profile, "192.0.2.100", cli.config, cli.ports,
        log_host="192.0.2.87", log_port=5514)
    assert not any(" deny " in command for command in repeated.commands)
    for command in repeated.commands:
        await cli.command(command)
    adapters.verify(repeated, cli.config, cli.ports)


@pytest.mark.parametrize("message", [CX_LOG, AOS_LOG, HP_LOG, CONTROLLER_LOG])
def test_real_vendor_event_shapes(message):
    result = logs.parse_message(message)
    assert result["action"] == "deny"
    assert result["source_address"] == "192.0.2.100"
    assert result["destination_address"] == "198.51.100.20"
    if message == CX_LOG:
        assert result["occurred_at"].utcoffset().total_seconds() == 10800
    else:
        assert result["occurred_at"] is None


@pytest.mark.parametrize("message", [
    b"authentication failed password=private",
    b"ACL configuration command created deny rule",
    b"interface 1/1/1 is down",
])
def test_non_acl_events_are_not_exposed(message):
    assert logs.parse_message(message) is None


def test_credentials_and_control_characters_are_redacted():
    result = logs.parse_message(b"ACL BLOCK deny src=192.0.2.100 password hidden-value\x1b")
    assert "hidden-value" not in result["message"]
    assert "\x1b" not in result["message"]


def test_peer_address_is_used_and_ambiguous_or_gateway_sources_are_rejected(admin_client, env, devices):
    create_group(admin_client, group_payload(devices["2930"]))
    stamp = now()
    with env() as db:
        source = db.get(m.Device, devices["2930"]).management_ip
    assert logs.ingest_batch([(source, AOS_LOG, "syslog_udp", stamp)]) == 1
    # Claimed hostname/address in payload cannot impersonate a managed device.
    assert logs.ingest_batch([("203.0.113.200", AOS_LOG, "syslog_udp", stamp)]) == 0
    with env() as db:
        db.get(m.Device, devices["2930"]).is_gateway = True
        db.commit()
    assert logs.ingest_batch([(source, AOS_LOG, "syslog_udp", stamp)]) == 0
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.ACLLog)) == 1


def test_filters_cursor_read_permissions_and_retention(admin_client, env, devices, monkeypatch):
    monkeypatch.setattr(logs, "redis_client", lambda: type("Redis", (), {"get": lambda self,key: None})())
    with env() as db:
        for index in range(55):
            db.add(m.ACLLog(device_id=devices["2930"], received_at=now(),
                peer_address="192.0.2.3", transport="syslog_udp", acl="BLOCK",
                source_address="192.0.2.100", action="deny", message=f"ACL BLOCK denied match {index}"))
        db.add(m.ACLLog(device_id=devices["2930"], received_at=now()-timedelta(days=31),
            peer_address="192.0.2.3", transport="syslog_udp", action="deny", message="expired"))
        db.commit()
    first = admin_client.get("/api/v1/blacklist/logs").json()
    assert len(first["items"]) == 50 and first["next"]
    second = admin_client.get("/api/v1/blacklist/logs", params=first["next"]).json()
    assert len(second["items"]) == 5
    assert not ({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
    assert admin_client.get("/api/v1/blacklist/logs?q=not-present").json()["items"] == []
    assert admin_client.get("/api/v1/blacklist/logs?before=2026-11-22T10:00:00").status_code == 422
    logs.prune()
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.ACLLog)) == 55
    admin_client.cookies.clear()
    assert admin_client.get("/api/v1/blacklist/logs").status_code == 401


@pytest.mark.parametrize("wire", [AOS_LOG+b"\n", str(len(AOS_LOG)).encode()+b" "+AOS_LOG])
async def test_tcp_line_and_octet_counted_frames(wire):
    reader = asyncio.StreamReader(limit=MAX_MESSAGE+1)
    reader.feed_data(wire)
    reader.feed_eof()
    assert await read_frame(reader) == AOS_LOG
    assert await read_frame(reader) is None


async def test_oversized_frames_and_full_queue_are_bounded():
    reader = asyncio.StreamReader(limit=MAX_MESSAGE+1)
    reader.feed_data(b"99999 ")
    with pytest.raises(ValueError):
        await read_frame(reader)
    receiver = Receiver()
    receiver.queue = asyncio.Queue(maxsize=1)
    receiver.enqueue("192.0.2.3", AOS_LOG, "syslog_udp")
    receiver.enqueue("192.0.2.3", AOS_LOG, "syslog_udp")
    receiver.enqueue("192.0.2.3", b"x"*(MAX_MESSAGE+1), "syslog_udp")
    assert receiver.queue.qsize() == 1
    assert receiver.dropped == 2


@pytest.mark.parametrize("adapter,profile", PROFILES)
def test_logging_target_conflict_preserves_existing_server(adapter, profile):
    config = base_config(adapter).replace("\nreturn\n", "\n")
    existing = "info-center loghost 192.0.2.87 port 514" if adapter == "hp_1950" else "logging 192.0.2.87"
    config += existing + "\n"
    if adapter == "hp_1950":
        config += "#\nreturn\n"
    from netrix.blacklist.cli import ACLError
    with pytest.raises(ACLError, match="başka portla"):
        adapters.build_plan(adapter, profile, "192.0.2.100", config, DeviceCLI(adapter).ports,
                            log_host="192.0.2.87", log_port=5515)


async def test_receiver_retries_storage_and_preserves_drop_counts(monkeypatch):
    from netrix.blacklist import log_receiver

    attempts = []

    def transient_failure(batch):
        attempts.append(batch)
        if len(attempts) < 3:
            raise RuntimeError('fixture transient storage failure')
        return 1

    async def no_delay(delay):
        pass

    monkeypatch.setattr(log_receiver, 'ingest_batch', transient_failure)
    monkeypatch.setattr(log_receiver.asyncio, 'sleep', no_delay)
    receiver = Receiver()
    receiver.enqueue('192.0.2.3', AOS_LOG, 'syslog_udp')
    stopping = asyncio.Event()
    stopping.set()
    await receiver.consume(stopping)
    assert len(attempts) == 3 and receiver.changed and receiver.dropped == 0

    attempts.clear()
    monkeypatch.setattr(log_receiver, 'ingest_batch', lambda batch: (_ for _ in ()).throw(RuntimeError('fixture permanent storage failure')))
    receiver.enqueue('192.0.2.3', AOS_LOG, 'syslog_udp')
    await receiver.consume(stopping)
    assert receiver.queue.empty() and receiver.dropped == 1


async def test_explicit_send_configures_logging_through_worker(admin_client, env, devices, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from netrix.blacklist import delivery
    from netrix.worker import claim, execute
    from test_blacklist_delivery import setup_submission

    entry_id = setup_submission(admin_client, env, devices['2930'])
    cli = LoggingCLI('aruba_2900')

    @asynccontextmanager
    async def connection(device, secret):
        yield cli

    monkeypatch.setattr(delivery, 'connect', connection)
    monkeypatch.setattr(delivery, 'settings', lambda: SimpleNamespace(
        acl_log_host='192.0.2.87', acl_log_port=5515, firmware_advertise_host=''))
    response = admin_client.post(f'/api/v1/blacklist/entries/{entry_id}/send')
    assert response.status_code == 202
    job_id = claim()
    await execute(job_id)
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.status == 'succeeded', job.error
    assert 'logging 192.0.2.87 udp 5515' in cli.saved
    assert 'deny ip host 192.0.2.100 any log' in cli.saved
    assert 'debug acl' in cli.commands


@pytest.mark.parametrize('message', [
    CX_LOG.replace(b'denied', b'permitted'),
    CONTROLLER_LOG.replace(b'action=deny', b'action=permit').replace(b'policy=BLOCK', b'policy=DENY'),
])
def test_permit_event_is_not_misclassified_by_acl_name(message):
    assert logs.parse_message(message)['action'] == 'permit'
