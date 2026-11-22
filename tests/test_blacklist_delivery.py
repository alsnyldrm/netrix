"""ACL writes are verified using stateful local CLI fixtures, never real devices."""

from contextlib import asynccontextmanager

import pytest
from netrix import models as m
from netrix.blacklist import adapters, delivery
from netrix.blacklist.cli import ACLError, Shell
from netrix.identity.security import encrypt
from netrix.worker import claim, execute
from sqlalchemy import select
from test_blacklist import create_group, group_payload
from test_blacklist import devices as devices

PROFILES = [
    ("aruba_5400", {"type": "standard", "name": "BLOCK", "number": None}),
    ("aruba_2900", {"type": "extended", "name": None, "number": 100}),
    ("aruba_6100", {"type": "ipv4", "name": "BLOCK", "number": None}),
    ("aruba_7200", {"type": "session", "name": "BLOCK", "number": None}),
    ("hp_1950", {"type": "basic", "name": None, "number": 2001}),
    ("hp_1950", {"type": "advanced", "name": "BLOCK", "number": 3001}),
]


def base_config(adapter):
    if adapter == "hp_1950":
        return "version 7.1\nsysname Fixture\n#\nreturn\n"
    if adapter in ("aruba_5400", "aruba_2900"):
        return "; Configuration Editor; Created on release WC.16.11\nhostname Fixture\n"
    return "version 10.13\nhostname Fixture\n"


def config_with(adapter, extra):
    config = base_config(adapter).replace("\nreturn\n", "\n") + extra
    if adapter == "hp_1950":
        config += "#\nreturn\n"
    return config


def port_output(adapter):
    return {
        "aruba_5400": "Port Type | Status\n A1 1000T | Up\n A2 1000T | Down\n",
        "aruba_2900": "Port Type | Status\n 1 1000T | Up\n 2 1000T | Down\n",
        "aruba_6100": "Port Name Status\n1/1/1 -- up\n1/1/2 -- down\n",
        "aruba_7200": "GE 0/0/0 is up\nGE 0/0/1 is down\n",
        "hp_1950": "Interface Link\nGE1/0/1 UP\nXGE1/0/49 DOWN\n",
    }[adapter]


class DeviceCLI:
    def __init__(self, adapter):
        self.adapter = adapter
        self.config = base_config(adapter)
        self.saved = self.config
        self.ports = port_output(adapter)
        self.commands = []
        self.context = None
        self.fail_binding = False
        self.fail_saved = False

    async def command(self, command, **kwargs):
        self.commands.append(command)
        running, ports, saved = delivery.READS[self.adapter]
        if command == running:
            return self.config
        if command == ports:
            return self.ports
        if command == saved:
            return base_config(self.adapter) if self.fail_saved else self.saved
        if command.startswith("show access-list ip "):
            return "IPv4 " + command.removeprefix("show access-list ip ")
        if command in ("write memory", "save force"):
            self.saved = self.config
            return ""
        if command in ("configure terminal", "system-view", "end", "return", "exit", "quit"):
            self.context = None
            return ""
        if command.startswith(
            ("interface ", "ip access-list ", "access-list ip ", "acl number ", "netdestination ")
        ):
            self.context = command
            return ""
        assert self.context, command
        if self.fail_binding and command.startswith(
            ("ip access-group ", "apply access-list ", "packet-filter ")
        ):
            raise ACLError("Fixture port binding failure")
        all_blocks = dict(adapters.blocks(self.config))
        content = all_blocks.setdefault(self.context, [])
        normalized = " ".join(adapters.words(command))
        if normalized not in content:
            content.append(normalized)
        self.config = base_config(self.adapter) + "".join(
            header + "\n" + "".join(" " + line + "\n" for line in body)
            for header, body in all_blocks.items()
            if header not in {h for h, _ in adapters.blocks(base_config(self.adapter))}
        )
        if self.adapter == "hp_1950":
            self.config = self.config.replace("\nreturn\n", "\n") + "#\nreturn\n"
        return ""


@pytest.mark.parametrize("adapter,profile", PROFILES)
async def test_new_acl_all_ports_saved_and_second_ip_keeps_existing_deny(adapter, profile):
    cli = DeviceCLI(adapter)
    for address in ("192.0.2.100", "192.0.2.101", "192.0.2.100"):
        plan = adapters.build_plan(adapter, profile, address, cli.config, cli.ports)
        for command in plan.commands:
            await cli.command(command)
        adapters.verify(plan, cli.config, cli.ports)
        await cli.command("save force" if adapter == "hp_1950" else "write memory")
        adapters.verify(plan, cli.saved, cli.ports)
        assert len(plan.physical_ports) == 2
    if adapter == "aruba_7200":
        body, hosts = adapters.session_rules(adapters.blocks(cli.config), plan.acl_header, plan.alias)
        assert hosts == {"192.0.2.100", "192.0.2.101"}
        assert body[-1] == "any any any permit"
    else:
        rules, permit = adapters.rules(
            adapter, profile, adapters.matching_acl(adapters.blocks(cli.config), plan.acl_header, adapter)
        )
        assert set(rules.values()) == {"192.0.2.100", "192.0.2.101"}
        assert len(rules) == 2 and permit


@pytest.mark.parametrize("adapter,profile", PROFILES)
def test_existing_acl_and_existing_port_policy_are_rejected_before_writes(adapter, profile):
    header, binding = adapters.acl_identity(adapter, profile)
    with pytest.raises(ACLError):
        adapters.build_plan(
            adapter,
            profile,
            "192.0.2.100",
            config_with(adapter, header + "\n description SOMEONE_ELSE\n"),
            port_output(adapter),
        )
    port = adapters.port_inventory(adapter, port_output(adapter), [])[0][0]
    if adapter == "aruba_6100":
        foreign = "apply access-list ip OTHER in"
    elif adapter == "hp_1950":
        foreign = "packet-filter 3999 inbound"
    else:
        foreign = "ip access-group OTHER in"
    with pytest.raises(ACLError, match="başka ACL"):
        adapters.build_plan(
            adapter,
            profile,
            "192.0.2.100",
            config_with(adapter, "interface " + port + "\n " + foreign + "\n"),
            port_output(adapter),
        )


def test_lag_members_are_covered_via_aggregate_and_member_conflicts_block():
    config = (
        base_config("aruba_6100")
        + "interface 1/1/1\n lag 1\ninterface 1/1/2\n lag 1\ninterface lag 1\n no shutdown\n"
    )
    plan = adapters.build_plan("aruba_6100", PROFILES[2][1], "192.0.2.100", config, port_output("aruba_6100"))
    assert plan.ports == ["lag 1"]
    assert "interface 1/1/1" not in plan.commands
    bad = config.replace(" lag 1\n", " lag 1\n apply access-list ip OTHER in\n", 1)
    with pytest.raises(ACLError):
        adapters.build_plan("aruba_6100", PROFILES[2][1], "192.0.2.100", bad, port_output("aruba_6100"))


class Process:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.stdout = self.stdin = self
        self.writes = []

    async def read(self, size):
        return next(self.responses, "")

    def write(self, value):
        self.writes.append(value)


async def test_shell_accepts_context_changes_and_sanitizes_command_errors():
    process = Process(
        ["switch#\n", "configure terminal\nswitch(config)#\n", "Error: hidden-password\nswitch(config)#\n"]
    )
    cli = Shell(process, "aruba_6100")
    await cli.read()
    await cli.command("configure terminal")
    with pytest.raises(ACLError) as error:
        await cli.command("bad")
    assert "hidden-password" not in str(error.value)
    assert adapters.blocks('ip access-list standard "BLOCK"\n 10 deny host 192.0.2.1\n exit\n') == [
        ("ip access-list standard BLOCK", ["10 deny host 192.0.2.1"])
    ]


def setup_submission(client, env, device_id, family=None, profile=None):
    with env() as db:
        credential = m.Credential(
            name="ACL fixture SSH",
            protocol="ssh",
            encrypted_secret=encrypt('{"username":"fixture","password":"fixture-only"}'),
        )
        db.add(credential)
        db.flush()
        db.get(m.Device, device_id).config_credential_id = credential.id
        db.commit()
    payload = group_payload(device_id)
    if family is not None:
        payload["profiles"] = {family: profile}
    group = create_group(client, payload)
    response = client.post(
        "/api/v1/blacklist/entries", json={"address": "192.0.2.100", "group_ids": [group["id"]]}
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("failure", ["", "binding", "saved"])
async def test_send_entry_runs_through_normal_worker_and_never_claims_unverified_success(
    admin_client, env, devices, monkeypatch, failure
):
    entry_id = setup_submission(admin_client, env, devices["2930"])
    cli = DeviceCLI("aruba_2900")
    cli.fail_binding = failure == "binding"
    cli.fail_saved = failure == "saved"

    @asynccontextmanager
    async def fake_connect(device, secret):
        assert secret["username"] == "fixture"
        yield cli

    monkeypatch.setattr(delivery, "connect", fake_connect)
    response = admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    assert response.status_code == 202, response.text
    again = admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    assert again.json() == response.json()
    job_id = claim()
    assert job_id == response.json()["job_ids"][0]
    await execute(job_id)
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.status == ("failed" if failure else "succeeded"), job.error
        assert job.active_key is None
    result = admin_client.get("/api/v1/blacklist/entries").json()["items"][0]
    assert result["devices"][0]["job"]["status"] == ("failed" if failure else "succeeded")
    assert result["state"] == ("failed" if failure else "blocked")
    assert result["devices"][0]["applied"] is (None if failure else True)


async def test_cancelled_and_reclassified_gateway_jobs_never_connect(admin_client, env, devices, monkeypatch):
    entry_id = setup_submission(admin_client, env, devices["2930"])
    response = admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    job_id = response.json()["job_ids"][0]
    admin_client.post("/api/v1/jobs/" + job_id + "/cancel")
    assert claim() is None
    response = admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    job_id = claim()
    with env() as db:
        db.get(m.Device, devices["2930"]).is_gateway = True
        db.commit()

    def forbidden(*args):
        raise AssertionError("Gateway must never receive an SSH connection")

    monkeypatch.setattr(delivery, "connect", forbidden)
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "failed"


def test_busy_device_does_not_starve_other_targets(admin_client, env, devices):
    entry_id = setup_submission(admin_client, env, devices["2930"])
    response = admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    active_id = claim()
    assert active_id == response.json()["job_ids"][0]
    with env() as db:
        blocked = m.Job(kind="backup", target_id=devices["2930"])
        other = m.Job(kind="identify", target_id=devices["6100"])
        db.add_all([blocked, other])
        db.commit()
        other_id = other.id
    assert claim() == other_id
    assert claim() is None


async def test_cancel_between_commands_and_retry_reconciles_partial_acl(
    admin_client, env, devices, monkeypatch
):
    entry_id = setup_submission(admin_client, env, devices["2930"])
    cli = DeviceCLI("aruba_2900")
    original = cli.command
    should_cancel = True

    async def command(value, **kwargs):
        nonlocal should_cancel
        result = await original(value, **kwargs)
        if value.startswith("60000 permit") and should_cancel:
            should_cancel = False
            with env() as db:
                job = db.scalar(select(m.Job).where(m.Job.active_key == "blacklist_send:" + devices["2930"]))
                job.cancel_requested = True
                db.commit()
        return result

    cli.command = command

    @asynccontextmanager
    async def fake_connect(device, secret):
        yield cli

    monkeypatch.setattr(delivery, "connect", fake_connect)
    admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    job_id = claim()
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "cancelled"
    assert "write memory" not in cli.commands
    admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    await execute(claim())
    with env() as db:
        assert db.scalar(select(m.Job).where(m.Job.kind == "blacklist_send", m.Job.status == "succeeded"))
    assert cli.saved.count("deny ip host 192.0.2.100") == 1


def test_aos_trunk_casing_does_not_hide_existing_port_acl():
    config = (
        base_config("aruba_5400")
        + "trunk a1-a2 trk1 lacp\ninterface Trk1\n ip access-group OTHER in\n exit\n"
    )
    with pytest.raises(ACLError, match="başka ACL"):
        adapters.build_plan("aruba_5400", PROFILES[0][1], "192.0.2.100", config, port_output("aruba_5400"))


@pytest.mark.parametrize("adapter,profile", PROFILES)
async def test_every_family_uses_normal_worker_entry_point(
    admin_client, env, devices, monkeypatch, adapter, profile
):
    from netrix.blacklist.service import ADAPTERS

    names = {
        "aruba_5400": "5412",
        "aruba_2900": "2930",
        "aruba_6100": "6100",
        "aruba_7200": "7205",
        "hp_1950": "1950",
    }
    entry_id = setup_submission(admin_client, env, devices[names[adapter]], ADAPTERS[adapter], profile)
    cli = DeviceCLI(adapter)

    @asynccontextmanager
    async def fake_connect(device, secret):
        yield cli

    monkeypatch.setattr(delivery, "connect", fake_connect)
    response = admin_client.post(f"/api/v1/blacklist/entries/{entry_id}/send")
    assert response.status_code == 202, response.text
    job_id = claim()
    await execute(job_id)
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.status == "succeeded", job.error
        assert job.result["phase"] == "verified"
        assert len(job.result["ports"]) == 2


@pytest.mark.parametrize(
    "adapter,prompts",
    [
        (
            "aruba_7200",
            ["(Controller) [md] #", "(Controller) [md] (config) #", "(Controller) [md] (config-sess-BLOCK)#"],
        ),
        ("aruba_6100", ["switch#", "switch(config)#", "switch(config-if-1/1/1)#"]),
        ("hp_1950", ["<Switch>", "[Switch]", "[Switch-acl-ipv4-basic-2001]"]),
    ],
)
async def test_configuration_prompt_transitions(adapter, prompts):
    process = Process([prompt + "\n" for prompt in prompts])
    cli = Shell(process, adapter)
    await cli.read()
    await cli.command("configure terminal" if adapter != "hp_1950" else "system-view")
    await cli.command("safe-command-fixture")


def test_modular_vsf_physical_port_names_are_preserved():
    output = "Port Type | Status\n 1/A1 1000T | Up\n 1/A2 1000T | Down\n"
    plan = adapters.build_plan("aruba_5400", PROFILES[0][1], "192.0.2.100", base_config("aruba_5400"), output)
    assert plan.physical_ports == ["1/A1", "1/A2"]
    assert "interface 1/A1" in plan.commands
