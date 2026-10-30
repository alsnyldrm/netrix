"""Synthetic CLI transcripts only; no network access or device credentials."""

import asyncio
from types import SimpleNamespace

import pytest
from netrix.configuration.validation import BackupError, require_ssh_backup
from netrix.discovery import protocols
from netrix.discovery.aruba import ARUBA_ADAPTERS, read_aruba
from netrix.discovery.identification import ssh_identity
from netrix.schemas import DeviceInput

CONFIGS = {
    "aruba_5400": '; J9850A Configuration Editor; Created on release #KB.16.11\nhostname "core"\nvlan 1\n exit',
    "aruba_2900": '; J9726A Configuration Editor; Created on release #WB.16.11\nhostname "edge"\nvlan 1\n exit',
    "aruba_6100": "!Version AOS-CX PL.10.14.0001\nhostname access\ninterface 1/1/1\n no shutdown",
    "aruba_7200": 'version 8.10\nhostname "controller"\nwlan ssid-profile "fixture"\n essid "fixture"',
}
IDENTITIES = {
    "aruba_5400": "Chassis: Aruba 5406R zl2 J9850A\nSerial Number: fixture",
    "aruba_2900": "Chassis: HP 2920-24G J9726A\nSerial Number: fixture",
    "aruba_6100": "Vendor : Aruba\nProduct Name : JL678A 6100 24G 4SFP+ Switch",
    "aruba_7200": "Aruba Operating System Software.\nArubaOS (MODEL: Aruba7210), Version 8.10.0.0",
}


class Shell:
    def __init__(self, responses, prompt="fixture#", initial=None, chunk_size=17):
        self.prompt, self.responses = prompt, responses
        self.buffer = initial if initial is not None else "\x1b[2JWelcome\r\n" + prompt
        self.stdout = self.stdin = self
        self.commands, self.closed, self.chunk_size = [], False, chunk_size

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def read(self, size):
        size = min(size, self.chunk_size)
        value, self.buffer = self.buffer[:size], self.buffer[size:]
        return value

    def write(self, command):
        self.commands.append(command)
        if command == " ":
            self.buffer += "\r\n" + self.prompt
        else:
            self.buffer += command.strip() + "\r\n" + self.responses[command.strip()] + "\r\n" + self.prompt


class Connection:
    def __init__(self, shell):
        self.shell = shell

    def create_process(self, **kwargs):
        assert kwargs["term_type"] == "vt100" and "stderr" in kwargs
        return self.shell

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.parametrize("adapter", ARUBA_ADAPTERS)
@pytest.mark.parametrize("trust", [False, True])
async def test_aruba_identity_and_backup_use_single_read_only_shell(env, monkeypatch, adapter, trust):
    from netrix.core import settings

    paging, identity = ARUBA_ADAPTERS[adapter]
    shells = []

    def connect(host, **kwargs):
        assert host == "192.0.2.1" and kwargs["port"] == 2222
        assert kwargs["known_hosts"] == (None if trust else settings().known_hosts)
        assert kwargs["client_keys"] == []
        shell = Shell(
            {paging: "", identity: IDENTITIES[adapter], "show running-config": CONFIGS[adapter]},
            prompt="(controller) [mynode] #" if adapter == "aruba_7200" else "fixture#",
        )
        shells.append(shell)
        return Connection(shell)

    monkeypatch.setattr(protocols.asyncssh, "connect", connect)
    device = SimpleNamespace(
        adapter=adapter, management_ip="192.0.2.1", config_port=2222, ssh_trust_host_key=trust
    )
    secret = {"username": "fixture", "password": "fixture-secret"}
    fields = await protocols.fetch_identity(device, secret)
    assert fields["model"] and fields["vendor"] in ("Aruba", "HPE")
    if adapter != "aruba_7200":
        assert fields["kind"] == "switch"
    assert await protocols.fetch_config(device, secret) == CONFIGS[adapter] + "\n"
    assert shells[0].commands == [paging + "\n", identity + "\n"]
    assert shells[1].commands == [paging + "\n", "show running-config\n"]
    assert all(shell.closed for shell in shells)
    assert require_ssh_backup(device, SimpleNamespace(protocol="ssh"))
    assert (
        DeviceInput(name="fixture", management_ip="192.0.2.1", vrf_id="fixture", adapter=adapter).adapter
        == adapter
    )


@pytest.mark.parametrize(
    "response",
    ["Invalid input: secret", "Permission denied secret", "-- MORE --", "", "hello", "hostname incomplete"],
)
async def test_invalid_or_paged_config_is_rejected_without_remote_text(response):
    shell = Shell({"no page": "", "show running-config": response})
    with pytest.raises(BackupError) as error:
        await read_aruba(Connection(shell), "aruba_5400", backup=True)
    assert "secret" not in str(error.value)
    assert shell.closed


async def test_paging_failure_stops_before_config_read():
    shell = Shell({"no page": "Invalid input: no page"})
    with pytest.raises(BackupError, match="komutu reddedildi"):
        await read_aruba(Connection(shell), "aruba_5400", backup=True)
    assert shell.commands == ["no page\n"] and shell.closed


async def test_operator_is_not_silently_elevated():
    shell = Shell({}, prompt="fixture>")
    with pytest.raises(BackupError, match="Manager/Enable"):
        await read_aruba(Connection(shell), "aruba_5400", backup=True)
    assert shell.commands == [] and shell.closed


async def test_aoss_press_any_key_banner_and_chunked_terminal_codes():
    shell = Shell(
        {"no page": "", "show modules": IDENTITIES["aruba_5400"]}, initial="Press any key to continue"
    )
    result = await read_aruba(Connection(shell), "aruba_5400")
    assert "Chassis:" in result and shell.commands[0] == " "


async def test_disconnect_before_prompt_does_not_save_partial_config():
    shell = Shell({}, initial="fixture")
    with pytest.raises(BackupError, match="eksik"):
        await read_aruba(Connection(shell), "aruba_5400", backup=True)
    assert shell.closed


async def test_response_limit_and_cancellation_close_shell():
    shell = Shell({"no page": "", "show modules": "x" * (256 * 1024 + 1)}, chunk_size=8192)
    with pytest.raises(BackupError, match="sınır"):
        await read_aruba(Connection(shell), "aruba_5400")
    assert shell.closed
    shell = Shell({})

    async def cancel(size):
        raise asyncio.CancelledError()

    shell.read = cancel
    with pytest.raises(asyncio.CancelledError):
        await read_aruba(Connection(shell), "aruba_5400")
    assert shell.closed


@pytest.mark.parametrize("adapter", ARUBA_ADAPTERS)
def test_adapter_selection_alone_does_not_invent_identity(adapter):
    assert ssh_identity(adapter, "unrecognized output") == {}


def test_multiple_chassis_do_not_overwrite_model():
    assert "model" not in ssh_identity("aruba_2900", "Chassis: Aruba 2930F\nChassis: Aruba 2930M")


@pytest.mark.parametrize("adapter", ARUBA_ADAPTERS)
def test_api_bulk_and_file_import_accept_aruba(admin_client, inventory, transfer_profiles, env, adapter):
    from netrix.inventory.csv_transfer import validate

    with env() as db:
        valid, errors = validate(
            db,
            [
                (
                    2,
                    {
                        "name": "Imported Aruba",
                        "management_ip": "192.0.2.1",
                        "vrf_id": "Global",
                        "snmp_credential_id": "SNMP-Profil-01",
                        "config_credential_id": "SSH-Profil-01",
                        "ssh_trust_host_key": "Hayır",
                        "site_id": "Site-01",
                        "lifecycle_status": "active",
                        "adapter": adapter,
                    },
                )
            ],
        )
        assert not errors and len(valid) == 1
        payload = valid[0][1]
    response = admin_client.post("/api/v1/devices", json=payload)
    assert response.status_code == 201, response.text
    device_id = response.json()["id"]
    assert response.json()["adapter"] == adapter
    response = admin_client.post(
        "/api/v1/inventory/devices/bulk",
        json={
            "ids": [device_id],
            "action": "update",
            "changes": {"adapter": adapter},
        },
    )
    assert response.status_code == 200, response.text
    response = admin_client.post("/api/v1/jobs", json={"kind": "backup", "target_id": device_id})
    assert response.status_code == 202, response.text
