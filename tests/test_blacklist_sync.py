"""Desired-state sync: removal, deletion, group deletion and ACL changes on fixture CLIs only."""

import re
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.blacklist import actions, adapters, delivery
from netrix.blacklist.cli import ACLError
from netrix.core import now
from netrix.identity.security import encrypt
from netrix.worker import claim, execute
from sqlalchemy import func, select
from test_blacklist import create_group, group_payload
from test_blacklist import devices as devices
from test_blacklist_delivery import PROFILES, DeviceCLI, base_config, config_with, port_output

ROOT = "/api/v1/blacklist"


class SyncCLI(DeviceCLI):
    """Adds the bounded no/undo forms used by NETRIX removal plans."""

    def rebuild(self, all_blocks):
        base_headers = {header for header, _ in adapters.blocks(base_config(self.adapter))}
        self.config = base_config(self.adapter) + "".join(
            header + "\n" + "".join(" " + line + "\n" for line in body)
            for header, body in all_blocks.items()
            if header not in base_headers
        )
        if self.adapter == "hp_1950":
            self.config = self.config.replace("\nreturn\n", "\n") + "#\nreturn\n"

    fail_removal = False

    async def command(self, command, **kwargs):
        if command.endswith(" position 1"):
            self.commands.append(command)
            parsed = dict(adapters.blocks(self.config))
            parsed[self.context].insert(1, command.removesuffix(" position 1"))
            self.rebuild(parsed)
            return ""
        if not command.startswith(("no ", "undo ")) or command in ("no page", "no paging"):
            return await super().command(command, **kwargs)
        self.commands.append(command)
        if self.fail_removal:
            raise ACLError("Fixture removal failure")
        target = command.split(" ", 1)[1]
        all_blocks = dict(adapters.blocks(self.config))
        if self.context is None:
            removed = [h for h in all_blocks if h == target or h.startswith(target + " ")]
            assert removed, command
            for header in removed:
                del all_blocks[header]
        else:
            body = all_blocks[self.context]
            if re.fullmatch(r"(?:rule )?\d+", target):
                kept = [line for line in body if not (line == target or line.startswith(target + " "))]
            else:
                kept = [line for line in body if line != target]
            assert len(kept) < len(body), command
            all_blocks[self.context] = kept
        self.rebuild(all_blocks)
        return ""


async def run(cli, plan):
    for command in plan.commands:
        await cli.command(command)


def acl_addresses(adapter, profile, config):
    header, _ = adapters.acl_identity(adapter, profile)
    parsed = adapters.blocks(config)
    if adapter == "aruba_7200":
        return adapters.session_rules(parsed, header, adapters.alias_for(header))[1]
    return set(adapters.rules(adapter, profile, adapters.matching_acl(parsed, header, adapter))[0].values())


@pytest.mark.parametrize("adapter,profile", PROFILES)
async def test_sync_removes_extra_addresses_and_empty_set_restores_device(adapter, profile):
    cli = SyncCLI(adapter)
    plan = adapters.build_sync_plan(adapter, profile, {"192.0.2.10", "192.0.2.11"}, cli.config, cli.ports)
    await run(cli, plan)
    adapters.verify(plan, cli.config, cli.ports)

    plan = adapters.build_sync_plan(adapter, profile, {"192.0.2.11", "192.0.2.12"}, cli.config, cli.ports)
    assert plan.added == ("192.0.2.12",) and plan.removed == ("192.0.2.10",)
    await run(cli, plan)
    adapters.verify(plan, cli.config, cli.ports)
    assert acl_addresses(adapter, profile, cli.config) == {"192.0.2.11", "192.0.2.12"}

    removal = adapters.build_sync_plan(adapter, profile, set(), cli.config, cli.ports)
    assert removal.removal and removal.removed == ("192.0.2.11", "192.0.2.12")
    await run(cli, removal)
    adapters.verify(removal, cli.config, cli.ports)
    header, bind = adapters.acl_identity(adapter, profile)
    assert bind not in cli.config
    assert adapters.matching_acl(adapters.blocks(cli.config), header, adapter) is None
    assert "netdestination" not in cli.config
    # Removal is idempotent: a clean device needs no commands.
    assert adapters.build_removal_plan(adapter, profile, cli.config).commands == []


@pytest.mark.parametrize("adapter,profile", PROFILES)
def test_removal_refuses_foreign_acl_and_unexpected_bindings(adapter, profile):
    header, bind = adapters.acl_identity(adapter, profile)
    with pytest.raises(ACLError):
        adapters.build_removal_plan(adapter, profile, config_with(adapter, header + "\n description OTHER\n"))
    port = adapters.port_inventory(adapter, port_output(adapter), [])[0][0]
    with pytest.raises(ACLError, match="ACL tanımı bulunamadı"):
        adapters.build_removal_plan(adapter, profile, config_with(adapter, f"interface {port}\n {bind}\n"))


def test_sync_removes_duplicate_rules_of_one_address():
    profile = PROFILES[1][1]
    header, _ = adapters.acl_identity("aruba_2900", profile)
    config = config_with(
        "aruba_2900",
        f"{header}\n 60000 remark NETRIX-BLACKLIST\n 10 deny ip host 192.0.2.10 any\n"
        " 20 deny ip host 192.0.2.10 any\n 60000 permit ip any any\n",
    )
    plan = adapters.build_sync_plan("aruba_2900", profile, {"192.0.2.10"}, config, port_output("aruba_2900"))
    assert "no 20" in plan.commands and "no 10" not in plan.commands


def prepare(client, env, device_id, payload=None):
    with env() as db:
        credential = m.Credential(
            name="ACL sync fixture",
            protocol="ssh",
            encrypted_secret=encrypt('{"username":"fixture","password":"fixture-only"}'),
        )
        db.add(credential)
        db.flush()
        db.get(m.Device, device_id).config_credential_id = credential.id
        db.commit()
    return create_group(client, payload or group_payload(device_id))


def add_entry(client, group_id, address):
    response = client.post(ROOT + "/entries", json={"address": address, "group_ids": [group_id]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def drain(env):
    while job_id := claim():
        await execute(job_id)
        with env() as db:
            job = db.get(m.Job, job_id)
            assert job.status == "succeeded", job.error


@pytest.fixture
def fixture_cli(monkeypatch):
    cli = SyncCLI("aruba_2900")

    @asynccontextmanager
    async def fake_connect(device, secret):
        yield cli

    monkeypatch.setattr(delivery, "connect", fake_connect)
    return cli


def entry_by_address(client, address):
    return next(item for item in client.get(ROOT + "/entries").json()["items"] if item["address"] == address)


async def test_remove_and_delete_entries_reconcile_device_and_remove_last_acl(
    admin_client, env, devices, fixture_cli
):
    group = prepare(admin_client, env, devices["2930"])
    first = add_entry(admin_client, group["id"], "192.0.2.100")
    second = add_entry(admin_client, group["id"], "192.0.2.101")
    response = admin_client.post(ROOT + "/entries/actions", json={"action": "send", "entry_ids": [first, second]})
    assert response.status_code == 202, response.text
    assert response.json()["devices"] == 1
    await drain(env)
    assert fixture_cli.saved.count("deny ip host") == 2
    assert entry_by_address(admin_client, "192.0.2.100")["state"] == "blocked"

    response = admin_client.post(ROOT + "/entries/actions", json={"action": "remove", "entry_ids": [first]})
    assert response.status_code == 202, response.text
    assert entry_by_address(admin_client, "192.0.2.100")["state"] in ("queued", "remove_pending")
    await drain(env)
    assert "192.0.2.100" not in fixture_cli.saved and "192.0.2.101" in fixture_cli.saved
    removed = entry_by_address(admin_client, "192.0.2.100")
    assert removed["status"] == "disabled" and removed["state"] == "disabled"

    response = admin_client.delete(ROOT + f"/entries/{second}")
    assert response.status_code == 202, response.text
    assert entry_by_address(admin_client, "192.0.2.101")["state"] in ("queued", "deleting")
    await drain(env)
    assert "BLOCKED_IPS" in fixture_cli.saved
    assert "ip access-group" in fixture_cli.saved
    assert "deny ip host" not in fixture_cli.saved
    addresses = {item["address"] for item in admin_client.get(ROOT + "/entries").json()["items"]}
    assert addresses == {"192.0.2.100"}
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.DeviceACLState)) == 1
        job = db.scalar(select(m.Job).order_by(m.Job.created_at.desc()))
        assert not job.result["acl_removed"] and job.result["phase"] == "verified"
        # History survives the deleted entry.
        assert db.scalar(select(func.count()).select_from(m.BlacklistDelivery)) == 3


async def test_never_sent_draft_is_deleted_without_device_job(admin_client, env, devices):
    group = prepare(admin_client, env, devices["2930"])
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    response = admin_client.delete(ROOT + f"/entries/{entry}")
    assert response.status_code == 202 and response.json()["deleted"] == 1
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert db.scalar(select(func.count()).select_from(m.BlacklistEntry)) == 0


async def test_group_delete_removes_acl_from_devices_then_deletes_group(
    admin_client, env, devices, fixture_cli
):
    group = prepare(admin_client, env, devices["2930"])
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    listed = admin_client.get(ROOT + "/groups").json()["items"][0]
    assert listed["applied_devices"] == 1 and listed["pending_devices"] == 0
    response = admin_client.delete(ROOT + f"/groups/{group['id']}")
    assert response.status_code == 200, response.text
    assert admin_client.get(ROOT + "/groups").json()["items"][0]["status"] == "deleting"
    assert admin_client.patch(ROOT + f"/groups/{group['id']}", json=group_payload(devices["2930"])).status_code == 409
    await drain(env)
    assert admin_client.get(ROOT + "/groups").json()["items"] == []
    assert "BLOCKED_IPS" not in fixture_cli.saved
    remaining = entry_by_address(admin_client, "192.0.2.100")
    assert remaining["group_ids"] == [] and remaining["state"] == "no_target"


async def test_acl_profile_change_removes_old_acl_before_creating_new(admin_client, env, devices, fixture_cli):
    group = prepare(admin_client, env, devices["2930"])
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    changed = admin_client.patch(
        ROOT + f"/groups/{group['id']}", json=group_payload(devices["2930"], acl="NEW_BLOCK")
    )
    assert changed.status_code == 200
    device = admin_client.get(ROOT + "/device-states").json()["items"][0]
    assert device["status"] == "pending" and device["applied_acl"] == "BLOCKED_IPS"
    response = admin_client.post(ROOT + f"/groups/{group['id']}/sync")
    assert response.status_code == 202 and response.json()["devices"] == 1
    await drain(env)
    assert "BLOCKED_IPS" not in fixture_cli.saved
    assert "ip access-list extended NEW_BLOCK" in fixture_cli.saved
    assert fixture_cli.saved.count("ip access-group NEW_BLOCK in") == 2
    device = admin_client.get(ROOT + "/device-states").json()["items"][0]
    assert device["status"] == "synced" and device["applied_acl"] == "NEW_BLOCK"


async def test_device_removed_from_group_is_cleaned_by_device_sync(admin_client, env, devices, fixture_cli):
    group = prepare(admin_client, env, devices["2930"])
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    admin_client.patch(ROOT + f"/groups/{group['id']}", json=group_payload(devices["5412"]))
    device = next(
        item for item in admin_client.get(ROOT + "/device-states").json()["items"]
        if item["device_id"] == devices["2930"]
    )
    assert device["will_remove_acl"] and device["status"] == "pending"
    response = admin_client.post(ROOT + "/device-states/sync", json={"device_ids": [devices["2930"]]})
    assert response.status_code == 202 and response.json()["devices"] == 1
    await drain(env)
    assert "BLOCKED_IPS" not in fixture_cli.saved


async def test_running_job_is_reused_and_picks_up_later_changes(admin_client, env, devices, fixture_cli):
    group = prepare(admin_client, env, devices["2930"])
    first = add_entry(admin_client, group["id"], "192.0.2.100")
    second = add_entry(admin_client, group["id"], "192.0.2.101")
    response = admin_client.post(ROOT + f"/entries/{first}/send")
    job_id = claim()
    original = fixture_cli.command
    sent = False

    async def command(value, **kwargs):
        nonlocal sent
        if value == "write memory" and not sent:
            sent = True
            again = admin_client.post(ROOT + f"/entries/{second}/send")
            assert again.json()["job_ids"] == response.json()["job_ids"]
        return await original(value, **kwargs)

    fixture_cli.command = command
    await execute(job_id)
    assert claim() is None
    assert "192.0.2.101" in fixture_cli.saved
    assert entry_by_address(admin_client, "192.0.2.101")["state"] == "blocked"


def test_bulk_create_skips_existing_and_rejects_invalid(admin_client, env, devices):
    group = prepare(admin_client, env, devices["2930"])
    add_entry(admin_client, group["id"], "192.0.2.100")
    bad = admin_client.post(
        ROOT + "/entries/bulk", json={"addresses": ["192.0.2.1", "nope"], "group_ids": [group["id"]]}
    )
    assert bad.status_code == 422 and "nope" in bad.text
    response = admin_client.post(
        ROOT + "/entries/bulk",
        json={"addresses": ["192.0.2.100", "192.0.2.102", " 192.0.2.102 ", "2001:db8::1"], "group_ids": [group["id"]]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["created"] == 2 and response.json()["skipped"] == ["192.0.2.100"]
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert set(db.scalars(select(m.BlacklistEntry.status))) == {"draft"}


async def test_expired_entry_is_disabled_and_removed_by_scheduler(admin_client, env, devices, fixture_cli):
    group = prepare(admin_client, env, devices["2930"])
    expires = (now() + timedelta(hours=1)).isoformat()
    response = admin_client.post(
        ROOT + "/entries", json={"address": "192.0.2.100", "group_ids": [group["id"]], "expires_at": expires}
    )
    entry = response.json()["id"]
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    assert "192.0.2.100" in fixture_cli.saved
    assert actions.expire_due(now() + timedelta(hours=2)) == 1
    await drain(env)
    assert "192.0.2.100" not in fixture_cli.saved
    assert entry_by_address(admin_client, "192.0.2.100")["state"] == "disabled"
    past = admin_client.patch(
        ROOT + f"/entries/{entry}",
        json={"address": "192.0.2.100", "group_ids": [group["id"]], "expires_at": "2020-01-01T00:00:00Z"},
    )
    assert past.status_code == 422


async def test_failed_removal_keeps_deleting_entry_until_state_is_forgotten(
    admin_client, env, devices, fixture_cli
):
    group = prepare(admin_client, env, devices["2930"])
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    fixture_cli.fail_removal = True
    admin_client.delete(ROOT + f"/entries/{entry}")
    job_id = claim()
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "failed"
    assert entry_by_address(admin_client, "192.0.2.100")["state"] == "delete_failed"
    assert admin_client.patch(
        ROOT + f"/entries/{entry}", json={"address": "192.0.2.100", "group_ids": [group["id"]]}
    ).status_code == 409
    response = admin_client.delete(ROOT + f"/device-states/{devices['2930']}")
    assert response.status_code == 200, response.text
    assert admin_client.get(ROOT + "/entries").json()["items"] == []


def test_send_requires_active_group_and_ipv4(admin_client, env, devices):
    group = prepare(admin_client, env, devices["2930"])
    entry = add_entry(admin_client, group["id"], "2001:db8::1")
    response = admin_client.post(ROOT + "/entries/actions", json={"action": "send", "entry_ids": [entry]})
    assert response.status_code == 422
    with env() as db:
        assert db.get(m.BlacklistEntry, entry).status == "draft"


def test_reads_are_passive(admin_client, env, devices):
    prepare(admin_client, env, devices["2930"])
    for path in ("/entries", "/groups", "/device-states"):
        assert admin_client.get(ROOT + path).status_code == 200
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0


@pytest.mark.parametrize("adapter,profile", PROFILES)
async def test_group_acl_can_be_prepared_before_any_ip(adapter, profile):
    cli = SyncCLI(adapter)
    for desired in (set(), {"192.0.2.10"}, set()):
        if adapter == "aruba_7200" and not desired:
            removal = adapters.build_removal_plan(adapter, profile, cli.config)
            await run(cli, removal)
        plan = adapters.build_sync_plan(adapter, profile, desired, cli.config, cli.ports, retain_empty=True)
        assert not plan.removal
        await run(cli, plan)
        adapters.verify(plan, cli.config, cli.ports)
        assert acl_addresses(adapter, profile, cli.config) == desired
        assert not any(c.startswith(("logging ", "debug ", "info-center ")) for c in cli.commands)


async def test_empty_group_sync_creates_acl_and_preserves_it_after_ip_removal(admin_client, env, devices, fixture_cli):
    group = prepare(admin_client, env, devices["2930"])
    response = admin_client.post(ROOT + f"/groups/{group['id']}/sync")
    assert response.status_code == 202 and response.json()["devices"] == 1
    await drain(env)
    assert "ip access-list extended BLOCKED_IPS" in fixture_cli.saved
    assert fixture_cli.saved.count("ip access-group BLOCKED_IPS in") == 2
    listed = admin_client.get(ROOT + "/groups").json()["items"][0]
    assert listed["active_entries"] == 0 and listed["pending_devices"] == 0 and listed["applied_devices"] == 1
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    assert "192.0.2.100" not in fixture_cli.saved
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    assert "192.0.2.100" in fixture_cli.saved
    admin_client.post(ROOT + "/entries/actions", json={"action":"remove", "entry_ids":[entry]})
    await drain(env)
    assert "192.0.2.100" not in fixture_cli.saved and "BLOCKED_IPS" in fixture_cli.saved
    admin_client.delete(ROOT + f"/groups/{group['id']}")
    await drain(env)
    assert "BLOCKED_IPS" not in fixture_cli.saved


async def test_controller_empty_group_roundtrip_through_worker(admin_client, env, devices, monkeypatch):
    cli = SyncCLI("aruba_7200")
    @asynccontextmanager
    async def connection(device, secret):
        yield cli
    monkeypatch.setattr(delivery, "connect", connection)
    group = prepare(admin_client, env, devices["7205"], {
        "name":"Controller", "device_ids":[devices["7205"]],
        "profiles":{"aruba_os":PROFILES[3][1]},
    })
    for _ in range(2):
        response = admin_client.post(ROOT + f"/groups/{group['id']}/sync")
        assert response.json()["devices"] == 1
        await drain(env)
    assert "any any any permit" in cli.saved and " deny" not in cli.saved
    entry = add_entry(admin_client, group["id"], "192.0.2.100")
    admin_client.post(ROOT + f"/entries/{entry}/send")
    await drain(env)
    assert "192.0.2.100" in cli.saved
    admin_client.post(ROOT + "/entries/actions", json={"action":"remove", "entry_ids":[entry]})
    await drain(env)
    assert "192.0.2.100" not in cli.saved and " deny" not in cli.saved
    assert "ip access-list session BLOCK" in cli.saved


@pytest.mark.parametrize("already_present", [False, True])
async def test_delete_group_checks_every_member_without_recorded_state(admin_client, env, devices, fixture_cli, already_present):
    group = prepare(admin_client, env, devices["2930"])
    if already_present:
        plan = adapters.build_sync_plan("aruba_2900", group["profiles"]["aos_switch"], set(), fixture_cli.config, fixture_cli.ports, retain_empty=True)
        await run(fixture_cli, plan)
        fixture_cli.saved = fixture_cli.config
    response = admin_client.delete(ROOT + f"/groups/{group['id']}")
    assert response.status_code == 200 and response.json()["devices"] == 1
    assert response.json()["deleted"] == 0
    assert admin_client.get(ROOT + "/groups").json()["items"][0]["status"] == "deleting"
    await drain(env)
    assert admin_client.get(ROOT + "/groups").json()["items"] == []
    assert "BLOCKED_IPS" not in fixture_cli.saved
    assert "show running-config" in fixture_cli.commands


def test_delete_group_keeps_unreachable_member_pending(admin_client, env, devices):
    group = create_group(admin_client, group_payload(devices["2930"]))
    response = admin_client.delete(ROOT + f"/groups/{group['id']}")
    assert response.status_code == 200 and response.json()["skipped"]
    assert response.json()["deleted"] == 0
    assert admin_client.get(ROOT + "/groups").json()["items"][0]["status"] == "deleting"


async def test_unrecorded_group_removal_can_retry_after_device_error(admin_client, env, devices, fixture_cli):
    group = prepare(admin_client, env, devices["2930"])
    plan = adapters.build_sync_plan("aruba_2900", group["profiles"]["aos_switch"], set(), fixture_cli.config, fixture_cli.ports, retain_empty=True)
    await run(fixture_cli, plan)
    fixture_cli.saved = fixture_cli.config
    fixture_cli.fail_removal = True
    admin_client.delete(ROOT + f"/groups/{group['id']}")
    job_id = claim()
    await execute(job_id)
    with env() as db:
        assert db.get(m.Job, job_id).status == "failed"
        assert db.get(m.DeviceACLState, devices["2930"]).attempted["profile"] == group["profiles"]["aos_switch"]
    fixture_cli.fail_removal = False
    admin_client.post(ROOT + f"/groups/{group['id']}/sync")
    await drain(env)
    assert admin_client.get(ROOT + "/groups").json()["items"] == []


async def test_cx_host_address_rendered_without_prefix_can_be_removed():
    adapter, profile = PROFILES[2]
    cli = SyncCLI(adapter)
    await run(cli, adapters.build_sync_plan(adapter, profile, {'10.3.0.3'}, cli.config, cli.ports))
    cli.config = cli.config.replace('10.3.0.3/32 any', '10.3.0.3 any')
    plan = adapters.build_sync_plan(adapter, profile, set(), cli.config, cli.ports, retain_empty=True)
    assert plan.removed == ('10.3.0.3',) and 'no 10' in plan.commands
    await run(cli, plan)
    adapters.verify(plan, cli.config, cli.ports)
    assert '10.3.0.3' not in cli.config
    assert '60000 permit any any any' in cli.config


@pytest.mark.parametrize('source', ['10.3.0.0/24', '10.3.0.0/255.255.255.0', '999.3.0.3', 'any'])
def test_cx_host_parser_does_not_accept_network_or_invalid_source(source):
    with pytest.raises(ACLError):
        adapters.rules('aruba_6100', PROFILES[2][1], ['60000 comment NETRIX-BLACKLIST', f'10 deny any {source} any', '60000 permit any any any'])
