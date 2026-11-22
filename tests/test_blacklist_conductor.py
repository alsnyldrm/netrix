"""Conductor node writes, lease isolation and managed-device readback; no device network."""

import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.blacklist import adapters, conductor, delivery
from netrix.blacklist.cli import ACLError, Shell
from netrix.worker import claim, execute
from sqlalchemy import select
from test_blacklist import devices as devices
from test_blacklist_delivery import Process, base_config
from test_blacklist_sync import ROOT, SyncCLI, add_entry, drain, prepare

HOST = "192.0.2.30"
TARGET = "192.0.2.23"
MAC = "02:00:00:00:00:23"
PARENT = "/md/Fixtures"
NODE = PARENT + "/" + MAC
PROFILE = {"type": "session", "name": "BLOCK", "number": None}


def table(headers, rows):
    widths = [max(len(str(row[i])) for row in [headers, *rows]) + 2 for i in range(len(headers))]

    def line(row):
        return "".join(str(value).ljust(width) for value, width in zip(row, widths)).rstrip()

    return (
        line(headers)
        + "\n"
        + line(["-" * (w - 2) for w in widths])
        + "\n"
        + "\n".join(line(row) for row in rows)
        + "\n"
    )


def mapping_tables(path=NODE, target=TARGET, mac=MAC):
    parent = path.rsplit("/", 1)[0]
    debug = table(
        ["IP Address", "MAC", "Name", "Nodepath", "Type", "Model", "Version", "Status"],
        [[target, mac, "Fixture", parent, "MD", "Aruba7205", "8.10", "up"]],
    )
    devices_table = table(["Device", "Model", "Nodepath"], [[mac, "A7205", parent]])
    hierarchy = table(
        ["Config Node", "Type", "Name"],
        [["/", "System", ""], ["/md", "System", ""], [parent, "Group", ""], [path, "Device", "Fixture"]],
    )
    return debug, devices_table, hierarchy


def unsaved(paths):
    return table(["Nodename"], [[path] for path in paths])


def status(config_id=10, complete=True):
    return table(
        [
            "IP Address",
            "IPv6 Address",
            "Name",
            "Location",
            "Type",
            "Model",
            "Version",
            "Status",
            "Configuration State",
            "Config Sync Time (sec)",
            "Config ID",
            "Release Type",
        ],
        [
            [
                TARGET,
                "None",
                "Fixture",
                "Office",
                "MD",
                "Aruba7205",
                "8.10",
                "up",
                "UPDATE SUCCESSFUL" if complete else "UPDATE REQUIRED",
                0,
                config_id,
                "LSR",
            ]
        ],
    )


def node_config(config):
    return (
        "\n".join(line for line in config.splitlines() if not line.startswith(("version ", "hostname ")))
        + "\n"
    )


class Registry:
    def __init__(self):
        self.locks = {}
        self.keys = []
        self.active = 0
        self.max_active = 0

    def lock(self, key, **kwargs):
        assert kwargs == {"timeout": 660, "thread_local": False}
        self.keys.append(key)
        owner = self
        underlying = self.locks.setdefault(key, threading.Lock())

        class Lock:
            held = False

            def acquire(self, *, blocking, blocking_timeout):
                assert blocking and blocking_timeout == 120
                self.held = underlying.acquire(timeout=2)
                if self.held:
                    owner.active += 1
                    owner.max_active = max(owner.max_active, owner.active)
                return self.held

            def owned(self):
                return self.held

            def release(self):
                owner.active -= 1
                self.held = False
                underlying.release()

        return Lock()


class Reader:
    def __init__(self):
        self.config = base_config("aruba_7200") + f"conductorip {HOST}\ncontroller-ip vlan 10\n"
        self.ports = "GE 0/0/0 is up\nGE 0/0/1 is down\n"
        self.commands = []

    async def command(self, command, **kwargs):
        self.commands.append(command)
        assert command in ("show running-config", "show interface"), command
        return self.config if command == "show running-config" else self.ports


class Writer:
    def __init__(self, reader):
        self.reader = reader
        self.cli = SyncCLI("aruba_7200")
        self.cli.config = reader.config
        self.committed = reader.config
        self.path = "/mm/mynode"
        self.cid = 10
        self.commands = []
        self.foreign_paths = []
        self.inherited = ""
        self.inject_pending = ""
        self.never_apply = False
        self.delay = 0
        self.pending_apply = None
        self.remap = False
        self.on_write = None

    def pending(self):
        old = dict(adapters.blocks(node_config(self.committed)))
        new = dict(adapters.blocks(node_config(self.cli.config)))
        lines = []
        for header, body in new.items():
            if header not in old or body != old[header]:
                lines += [header, *[" " + line for line in body], "!"]
        lines += ["no " + header for header in old if header not in new]
        return "\n".join(lines) + self.inject_pending

    async def command(self, command, **kwargs):
        self.commands.append((self.path, command))
        if command == "show switches debug":
            path = NODE if not self.remap else "/md/Elsewhere/" + MAC
            return mapping_tables(path)[0]
        if command == "show configuration devices":
            path = NODE if not self.remap else "/md/Elsewhere/" + MAC
            return mapping_tables(path)[1]
        if command == "show configuration node-hierarchy":
            path = NODE if not self.remap else "/md/Elsewhere/" + MAC
            return mapping_tables(path)[2]
        if command == "show configuration unsaved-nodes":
            return unsaved([*self.foreign_paths, *([NODE] if self.pending().strip() else [])])
        if command == "pwd":
            return self.path
        if command.startswith("cd "):
            self.path = command[3:]
            assert self.path == NODE
            return ""
        if command == "show switches":
            if self.pending_apply and not self.never_apply:
                if self.delay:
                    self.delay -= 1
                else:
                    self.reader.config = self.pending_apply
                    self.pending_apply = None
            return status(self.cid)
        assert self.path == NODE, (self.path, command)
        if command == "show configuration pending":
            return self.pending()
        if command == "show configuration committed":
            return node_config(self.committed)
        if command == "show configuration effective":
            return node_config(self.committed) + self.inherited
        if command == "show configuration effective detail":
            config = node_config(self.committed)
            return (
                "\n".join(
                    line + f" # local [{NODE}]" if line.strip() not in ("", "!") else line
                    for line in config.splitlines()
                )
                + self.inherited
            )
        if command == "write memory":
            assert kwargs.get("save")
            self.committed = self.cli.config
            self.cid += 1
            self.pending_apply = self.committed
            return "Saved Configuration"
        if self.on_write:
            await self.on_write(command)
        committed = dict(adapters.blocks(self.committed))
        if command.startswith("ip access-group session "):
            if "ip access-list session " + command.split()[-1] not in committed:
                raise ACLError("Invalid access group configuration")
        if command.startswith("alias "):
            if "netdestination " + command.split()[1] not in committed:
                raise ACLError("Alias dependency is not committed")
        if command.startswith("no ip access-list session "):
            bind = "ip access-group session " + command.split()[-1]
            if any(bind in body for header, body in committed.items() if header.startswith("interface ")):
                raise ACLError("Committed interface still references ACL")
        if command.startswith("interface gigabitethernet "):
            result = await self.cli.command(command, **kwargs)
            if command not in dict(adapters.blocks(self.cli.config)):
                await self.cli.command("description GE" + command.split()[-1])
            return result
        return await self.cli.command(command, **kwargs)


@pytest.fixture
def routed(admin_client, env, devices, monkeypatch):
    group = prepare(
        admin_client,
        env,
        devices["7205"],
        {
            "name": "Controller",
            "device_ids": [devices["7205"]],
            "profiles": {"aruba_os": PROFILE},
        },
    )
    with env() as db:
        target = db.get(m.Device, devices["7205"])
        target.management_ip = TARGET
        master = m.Device(
            name="Conductor",
            management_ip=HOST,
            adapter="aruba_7200",
            model="ArubaMM-VA",
            vrf_id=target.vrf_id,
            config_credential_id=target.config_credential_id,
            kind="switch",
        )
        db.add(master)
        db.commit()
        master_id = master.id
    monkeypatch.setattr(conductor, "settings", lambda: SimpleNamespace(blacklist_conductor_host=HOST))
    monkeypatch.setattr(conductor, "SYNC_TIMEOUT", 0.05)
    monkeypatch.setattr(conductor, "POLL_INTERVAL", 0.001)
    registry = Registry()
    monkeypatch.setattr(conductor, "redis_client", lambda: registry)
    reader = Reader()
    writer = Writer(reader)

    @asynccontextmanager
    async def connection(device, secret):
        assert secret["username"] == "fixture"
        yield writer if device.management_ip == HOST else reader

    monkeypatch.setattr(delivery, "connect", connection)
    return SimpleNamespace(
        group=group,
        reader=reader,
        writer=writer,
        registry=registry,
        master_id=master_id,
        device_id=devices["7205"],
    )


def test_device_node_comes_from_hierarchy_not_debug_group_path():
    assert conductor.resolve_node(*mapping_tables(), TARGET) == conductor.Node(NODE, MAC)


@pytest.mark.parametrize("path", ["/md", "/md/../" + MAC, "/mm/" + MAC, "/md/group;write/" + MAC])
def test_non_device_or_unsafe_node_is_rejected(path):
    with pytest.raises(ACLError):
        conductor.resolve_node(*mapping_tables(path), TARGET)


def test_conflicting_identity_or_duplicate_target_is_rejected():
    debug, devices_table, hierarchy = mapping_tables()
    with pytest.raises(ACLError):
        conductor.resolve_node(debug, devices_table.replace(MAC, "02:00:00:00:00:99"), hierarchy, TARGET)
    with pytest.raises(ACLError):
        conductor.resolve_node(debug + debug.splitlines()[-1] + "\n", devices_table, hierarchy, TARGET)


async def test_own_and_global_config_prompt_markers_are_accepted():
    for prompt in ["(mm) ^[02:00:00:00:00:23] (config-sess-BLOCK) #", "(mm) *[mynode] #"]:
        output, actual = await Shell(Process(["ok\n" + prompt]), "aruba_7200").read()
        assert output == "ok" and actual == prompt


async def test_full_acl_and_ip_lifecycle_uses_only_target_node(admin_client, env, routed):
    group = routed.group
    first = admin_client.post(ROOT + f"/groups/{group['id']}/sync")
    assert first.status_code == 202 and first.json()["devices"] == 1
    await drain(env)
    assert "ip access-list session BLOCK" in routed.reader.config
    assert " deny" not in routed.reader.config
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    assert "192.0.2.100" in routed.reader.config
    admin_client.post(ROOT + "/entries/actions", json={"action": "remove", "entry_ids": [entry]})
    await drain(env)
    assert (
        "192.0.2.100" not in routed.reader.config and "ip access-list session BLOCK" in routed.reader.config
    )
    admin_client.delete(ROOT + f"/groups/{group['id']}")
    await drain(env)
    assert "ip access-list session BLOCK" not in routed.reader.config
    writes = [
        (path, cmd)
        for path, cmd in routed.writer.commands
        if not cmd.startswith(("show ", "cd ")) and cmd != "pwd"
    ]
    assert writes and all(path == NODE for path, cmd in writes)
    assert all(cmd in ("show running-config", "show interface") for cmd in routed.reader.commands)
    assert all(key == "netrix:blacklist:conductor:" + routed.master_id for key in routed.registry.keys)
    with env() as db:
        last = db.scalar(select(m.Job).order_by(m.Job.created_at.desc()))
        assert last.result["conductor_ip"] == HOST and last.result["node_path"] == NODE
        assert db.get(m.DeviceACLState, routed.device_id) is None


@pytest.mark.parametrize(
    "failure", ["parent_pending", "inherited_acl", "foreign_pending", "remap", "no_readback"]
)
async def test_no_unverified_or_shared_change_is_committed(admin_client, env, routed, failure):
    if failure == "parent_pending":
        routed.writer.foreign_paths = [PARENT]
    if failure == "inherited_acl":
        routed.writer.inherited = (
            "ip access-list session BLOCK\n description NETRIX-BLACKLIST\n any any any permit\n!\n"
        )

    async def on_write(command):
        if command == "end":
            if failure == "foreign_pending":
                routed.writer.inject_pending = "\nlogging 203.0.113.10\n"
            if failure == "remap":
                routed.writer.remap = True

    routed.writer.on_write = on_write
    if failure == "no_readback":
        routed.writer.never_apply = True
    response = admin_client.post(ROOT + f"/groups/{routed.group['id']}/sync")
    assert response.status_code == 202
    job_id = claim()
    await execute(job_id)
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.status == "failed", job.result
        row = db.get(m.DeviceACLState, routed.device_id)
        assert row is None or row.status == "dirty"
    if failure != "no_readback":
        assert not any(cmd == "write memory" for path, cmd in routed.writer.commands)
    assert all(cmd in ("show running-config", "show interface") for cmd in routed.reader.commands)


async def test_delayed_managed_apply_is_polled_before_success(admin_client, env, routed):
    routed.writer.delay = 2
    admin_client.post(ROOT + f"/groups/{routed.group['id']}/sync")
    await drain(env)
    assert "ip access-list session BLOCK" in routed.reader.config


@pytest.mark.parametrize("foreign", [False, True])
async def test_resume_recorded_empty_acl_pending_without_committing_foreign_changes(
    admin_client, env, routed, foreign
):
    await routed.writer.command("cd " + NODE)
    for command in [
        "configure terminal",
        "ip access-list session BLOCK",
        "description NETRIX-BLACKLIST",
        "any any any permit",
        "exit",
        "interface gigabitethernet 0/0/0",
        "exit",
        "end",
    ]:
        await routed.writer.command(command)
    if foreign:
        routed.writer.inject_pending = "\nlogging 203.0.113.10\n"
    with env() as db:
        db.add(
            m.DeviceACLState(
                device_id=routed.device_id,
                status="dirty",
                profile=None,
                addresses=[],
                group_ids=[],
                attempted={"profile": PROFILE, "addresses": [], "group_ids": [routed.group["id"]]},
            )
        )
        db.commit()
    admin_client.post(ROOT + f"/groups/{routed.group['id']}/sync")
    job_id = claim()
    await execute(job_id)
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.status == ("failed" if foreign else "succeeded"), job.error
    commits = [cmd for path, cmd in routed.writer.commands if cmd == "write memory"]
    if foreign:
        assert not commits
    else:
        assert commits
        assert "ip access-group session BLOCK" in routed.reader.config
        assert not routed.writer.pending().strip()


async def test_changed_conductor_access_snapshot_never_opens_ssh(admin_client, env, routed, monkeypatch):
    admin_client.post(ROOT + f"/groups/{routed.group['id']}/sync")
    with env() as db:
        db.get(m.Device, routed.master_id).config_port = 2222
        db.commit()

    def forbidden(*args):
        raise AssertionError("Changed route must not connect")

    monkeypatch.setattr(delivery, "connect", forbidden)
    job_id = claim()
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "failed"


async def test_cancel_after_commands_never_commits_pending_changes(admin_client, env, routed):
    async def cancel(command):
        if command == "end":
            with env() as db:
                job = db.scalar(
                    select(m.Job).where(m.Job.active_key == delivery.ACTIVE_KEY + routed.device_id)
                )
                job.cancel_requested = True
                db.commit()

    routed.writer.on_write = cancel
    admin_client.post(ROOT + f"/groups/{routed.group['id']}/sync")
    job_id = claim()
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "cancelled"
    assert not any(cmd == "write memory" for path, cmd in routed.writer.commands)


@pytest.mark.parametrize("failure", ["access_changed", "lease_lost", "late_pending"])
async def test_commit_rechecks_access_lease_and_pending(admin_client, env, routed, monkeypatch, failure):
    original_progress = delivery.progress
    original_owned = Registry.lock

    def progress(job_id, phase, **values):
        if phase == "saving":
            if failure == "access_changed":
                with env() as db:
                    db.get(m.Device, routed.master_id).config_port = 2222
                    db.commit()
            elif failure == "late_pending":
                routed.writer.inject_pending = "\nlogging 203.0.113.10\n"
            else:
                for lock in locks:
                    lock.owned = lambda: False
        return original_progress(job_id, phase, **values)

    locks = []

    def capture_lock(self, *args, **kwargs):
        lock = original_owned(self, *args, **kwargs)
        locks.append(lock)
        return lock

    monkeypatch.setattr(Registry, "lock", capture_lock)
    monkeypatch.setattr(delivery, "progress", progress)
    admin_client.post(ROOT + f"/groups/{routed.group['id']}/sync")
    job_id = claim()
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "failed"
    assert not any(cmd == "write memory" for path, cmd in routed.writer.commands)


async def test_shared_conductor_lease_serializes_concurrent_tasks(monkeypatch):
    registry = Registry()
    monkeypatch.setattr(conductor, "redis_client", lambda: registry)
    route = SimpleNamespace(device=SimpleNamespace(id="master"))
    events = []

    async def run_job(number):
        async with conductor.lease(route):
            events.append(("start", number))
            await asyncio.sleep(0.005)
            events.append(("end", number))

    await asyncio.gather(run_job(1), run_job(2))
    assert registry.max_active == 1 and events[0][0] == "start" and events[1][0] == "end"
