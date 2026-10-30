"""Synthetic HP Comware transcripts; real network access remains blocked."""

import asyncio
import io
from types import SimpleNamespace

import pytest
from netrix.configuration.diff import redact_config
from netrix.configuration.validation import BackupError, require_ssh_backup
from netrix.discovery import protocols
from netrix.discovery.comware import read_comware
from netrix.discovery.identification import ssh_identity
from openpyxl import load_workbook
from test_aruba_adapters import Connection, Shell
from test_aruba_adapters import test_api_bulk_and_file_import_accept_aruba as check_import

CONFIG = "#\n version 7.1.070, Release 3506P11\n#\n sysname edge\n#\n local-user operator\n password cipher fixture-secret\n#\nreturn"
VERSION = "HPE Comware Platform Software\nHPE 1950-24G-2SFP+-2XGT Switch uptime is 4 weeks, 1 day\n"
ERROR = "% Unrecognized command found at '^' position."


@pytest.mark.parametrize("trust", [False, True])
async def test_hp1950_identity_backup_and_host_key_policy(env, monkeypatch, trust):
    from netrix.core import settings

    shells = []

    def connect(host, **kwargs):
        assert host == "192.0.2.1" and kwargs["port"] == 2222
        assert kwargs["known_hosts"] == (None if trust else settings().known_hosts)
        assert kwargs["client_keys"] == []
        shell = Shell(
            {
                "screen-length disable": "",
                "display version": VERSION,
                "display current-configuration": CONFIG,
            },
            prompt="<HP 1950>",
            chunk_size=1,
        )
        shells.append(shell)
        return Connection(shell)

    monkeypatch.setattr(protocols.asyncssh, "connect", connect)
    device = SimpleNamespace(
        adapter="hp_1950", management_ip="192.0.2.1", config_port=2222, ssh_trust_host_key=trust
    )
    secret = {"username": "fixture", "password": "fixture-secret"}
    assert await protocols.fetch_identity(device, secret) == {
        "vendor": "HPE",
        "model": "HPE 1950-24G-2SFP+-2XGT Switch",
        "kind": "switch",
    }
    assert await protocols.fetch_config(device, secret) == CONFIG + "\n"
    assert shells[0].commands == ["screen-length disable\n", "display version\n"]
    assert shells[1].commands == ["screen-length disable\n", "display current-configuration\n"]
    assert all(shell.closed for shell in shells)
    assert require_ssh_backup(device, SimpleNamespace(protocol="ssh"))
    assert "fixture-secret" not in redact_config(CONFIG)


@pytest.mark.parametrize(
    "response", [ERROR + " fixture-secret", "", "hello", CONFIG[:-6], CONFIG + "\n-- More --"]
)
async def test_invalid_or_incomplete_config_never_becomes_backup(response):
    shell = Shell({"screen-length disable": "", "display current-configuration": response}, prompt="<edge>")
    with pytest.raises(BackupError) as exc:
        await read_comware(Connection(shell), backup=True)
    assert "fixture-secret" not in str(exc.value) and shell.closed


async def test_limited_cli_falls_back_to_summary_for_identity_but_cannot_backup():
    responses = {
        "screen-length disable": ERROR,
        "summary": "Device description : HPE 1950-24G-2SFP+-2XGT Switch",
    }
    shell = Shell(responses, prompt="<HP>")
    fields = ssh_identity("hp_1950", await read_comware(Connection(shell)))
    assert fields == {"vendor": "HPE", "model": "HPE 1950-24G-2SFP+-2XGT Switch", "kind": "switch"}
    assert shell.commands == ["screen-length disable\n", "summary\n"]
    shell = Shell(responses, prompt="<HP>")
    with pytest.raises(BackupError) as exc:
        await read_comware(Connection(shell), backup=True)
    assert exc.value.code == "comware_cli_required"
    assert shell.commands == ["screen-length disable\n"] and shell.closed


async def test_unavailable_display_version_falls_back_to_summary():
    shell = Shell(
        {"screen-length disable": "", "display version": ERROR, "summary": "Device summary"}, prompt="<HP>"
    )
    assert await read_comware(Connection(shell)) == "Device summary\n"
    assert shell.commands == ["screen-length disable\n", "display version\n", "summary\n"]


async def test_disconnect_limit_timeout_and_cancellation_close_shell():
    shell = Shell({}, initial="<partial")
    with pytest.raises(BackupError, match="eksik"):
        await read_comware(Connection(shell))
    assert shell.closed
    shell = Shell(
        {"screen-length disable": "", "display version": "x" * (256 * 1024 + 1)},
        prompt="<HP>",
        chunk_size=8192,
    )
    with pytest.raises(BackupError, match="sınır"):
        await read_comware(Connection(shell))
    assert shell.closed
    for error in (TimeoutError, asyncio.CancelledError):
        shell = Shell({}, prompt="<HP>")

        async def stop(size):
            raise error()

        shell.read = stop
        with pytest.raises(error):
            await read_comware(Connection(shell))
        assert shell.closed


def test_unknown_or_ambiguous_identity_does_not_invent_model():
    assert ssh_identity("hp_1950", "Welcome\nSystem name : HP 1950") == {"vendor": "HPE"}
    assert ssh_identity("hp_1950", "Unrecognized output") == {}
    assert "model" not in ssh_identity("hp_1950", VERSION + "HPE 1950-48G-2SFP+-2XGT Switch uptime is 3 days")


def test_hp1950_api_bulk_csv_xlsx_and_protocol_choices(admin_client, inventory, transfer_profiles, env):
    check_import(admin_client, inventory, transfer_profiles, env, "hp_1950")
    device = admin_client.get("/api/v1/devices").json()["items"][0]
    options = admin_client.get(f"/api/v1/devices/{device['id']}/connection-tests").json()
    assert options["can_test"]
    assert next(p for p in options["protocols"] if p["protocol"] == "ssh")["enabled"]
    assert not next(p for p in options["protocols"] if p["protocol"] == "rest")["enabled"]
    book = load_workbook(io.BytesIO(admin_client.get("/api/v1/inventory/devices/xlsx/template").content))
    names = book.defined_names["netrix_adapter"]
    values = [cell.value for sheet, cells in names.destinations for row in book[sheet][cells] for cell in row]
    assert "HP 1950 · Comware 7" in values


class ExtendedShell(Shell):
    def __init__(self, *, direct=False, failure=False):
        super().__init__({"display current-configuration": CONFIG}, prompt="<HP1950>", chunk_size=3)
        self.extended, self.direct, self.failure = False, direct, failure

    def write(self, value):
        self.commands.append(value)
        value = value.strip()
        if value == "xtd-cli-mode":
            self.buffer += (
                "Password:"
                if self.direct
                else "All commands can be displayed and executed in extended CLI mode. Switch to extended CLI\nmode? [Y/N]:"
            )
        elif value == "y":
            self.buffer += "\r\nPlease input password:"
        elif value == "fixture-cli-secret":
            self.extended = not self.failure
            self.buffer += (
                ("\r\nInvalid password fixture-cli-secret" if self.failure else "") + "\r\n" + self.prompt
            )
        elif value == "screen-length disable":
            self.buffer += value + "\r\n" + ("" if self.extended else ERROR) + "\r\n" + self.prompt
        else:
            self.buffer += value + "\r\n" + self.responses[value] + "\r\n" + self.prompt


@pytest.mark.parametrize("direct", [False, True])
async def test_extended_cli_uses_only_saved_secret_and_read_commands(direct):
    shell = ExtendedShell(direct=direct)
    assert (
        await read_comware(Connection(shell), backup=True, cli_password="fixture-cli-secret") == CONFIG + "\n"
    )
    assert shell.commands == ["screen-length disable\n", "xtd-cli-mode\n"] + ([] if direct else ["y\n"]) + [
        "fixture-cli-secret\n",
        "screen-length disable\n",
        "display current-configuration\n",
    ]
    assert shell.closed


async def test_extended_cli_failure_never_leaks_secret_or_reads_config():
    shell = ExtendedShell(failure=True)
    with pytest.raises(BackupError) as exc:
        await read_comware(Connection(shell), backup=True, cli_password="fixture-cli-secret")
    assert exc.value.code == "comware_cli_auth" and "fixture-cli-secret" not in str(exc.value)
    assert "display current-configuration\n" not in shell.commands and shell.closed


def test_cli_secret_encrypted_hidden_rotated_and_rejects_terminal_injection(admin_client, env):
    from netrix import models as m
    from netrix.identity.security import secret_data

    payload = {
        "name": "HP 1950 SSH",
        "protocol": "ssh",
        "secret": {
            "username": "operator",
            "password": "fixture-login-secret",
            "cli_password": "fixture-cli-secret",
        },
    }
    response = admin_client.post("/api/v1/credentials", json=payload)
    assert response.status_code == 201
    profile_id = response.json()["id"]
    with env() as db:
        profile = db.get(m.Credential, profile_id)
        assert "fixture-cli-secret" not in profile.encrypted_secret
        assert secret_data(profile)["cli_password"] == "fixture-cli-secret"
    for resource in ("credentials", "audit", "events"):
        assert "fixture-cli-secret" not in admin_client.get("/api/v1/" + resource).text
    payload["secret"]["cli_password"] = "updated-cli-secret"
    assert admin_client.put("/api/v1/credentials/" + profile_id, json=payload).status_code == 200
    with env() as db:
        assert secret_data(db.get(m.Credential, profile_id))["cli_password"] == "updated-cli-secret"
    payload["secret"]["cli_password"] = "fixture-cli-secret\nreboot"
    response = admin_client.put("/api/v1/credentials/" + profile_id, json=payload)
    assert response.status_code == 422 and "fixture-cli-secret" not in response.text
    with env() as db:
        assert secret_data(db.get(m.Credential, profile_id))["cli_password"] == "updated-cli-secret"
