"""Protocol interactions, precise image selection and unsafe prompt rejection."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from netrix.firmware import adapters


class Terminal:
    def __init__(self, responses, prompt="switch# "):
        self.queue = asyncio.Queue()
        self.queue.put_nowait(prompt)
        self.responses = responses
        self.writes = []
        self.stdin = self
        self.stdout = self

    def write(self, value):
        self.writes.append(value)
        chunks = self.responses.get(value, [])
        for chunk in chunks:
            self.queue.put_nowait(chunk)

    async def read(self, size):
        return await self.queue.get()


@pytest.mark.asyncio
async def test_cx_transfer_pins_source_host_key_and_sends_password_only_to_password_prompt():
    key = "SHA256:source-fixture-key"
    terminal = Terminal(
        {
            "copy fixture\n": [
                f"The authenticity of host cannot be established. Key fingerprint is {key}.\nAre you sure you want to continue connecting (yes/no/[fingerprint])? "
            ],
            "yes\n": ["user@host's pass", "word: "],
            "temporary-password\n": ["\nVerifying and writing system firmware...\nswitch# "],
        }
    )
    cli = adapters.CLI(terminal, "aruba_6100", key_fingerprints=(key,))
    await cli.read()
    await cli.command("copy fixture", action="transfer", password="temporary-password")
    assert terminal.writes == ["copy fixture\n", "yes\n", "temporary-password\n"]


@pytest.mark.asyncio
async def test_unknown_source_host_key_is_never_accepted():
    terminal = Terminal(
        {
            "copy fixture\n": [
                "The authenticity of host cannot be established. Key fingerprint is SHA256:wrong.\nAre you sure you want to continue connecting (yes/no)? "
            ]
        }
    )
    cli = adapters.CLI(terminal, "aruba_6100", key_fingerprints=("SHA256:expected",))
    await cli.read()
    with pytest.raises(adapters.FirmwareError, match="anahtarı"):
        await cli.command("copy fixture", action="transfer", password="never-send-this")
    assert terminal.writes == ["copy fixture\n"]


@pytest.mark.asyncio
async def test_read_only_command_cannot_answer_yes_or_send_password():
    for prompt in ("Continue? [Y/N]: ", "Password: "):
        terminal = Terminal({"show version\n": [prompt]})
        cli = adapters.CLI(terminal, "aruba_6100")
        await cli.read()
        with pytest.raises(adapters.FirmwareError):
            await cli.command("show version")
        assert terminal.writes == ["show version\n"]


@pytest.mark.asyncio
async def test_aoss_waits_for_new_flash_completion_event_even_if_same_version_already_in_bank(
    tmp_path, monkeypatch
):
    path = tmp_path / "image.swi"
    content = b"firmware\x00\xff" * 100
    path.write_bytes(content)
    captured = bytearray()
    calls = []
    log_calls = 0

    class Writer:
        async def write(self, data):
            captured.extend(data)

    class SFTP:
        @asynccontextmanager
        async def open(self, path, mode):
            assert path == "/os/secondary" and mode == "wb"
            yield Writer()

    class Connection:
        @asynccontextmanager
        async def start_sftp_client(self):
            yield SFTP()

    class CLI:
        async def command(self, value):
            nonlocal log_calls
            calls.append(value)
            if value == "show logging -r":
                log_calls += 1
                return (
                    "I 11/02/26 12:01:02 00150 update: Secondary Image updated."
                    if log_calls >= 3
                    else "old event"
                )
            return "Secondary Image : 5000 bytes WC.16.11.0026"

    async def sleep(*args):
        pass

    monkeypatch.setattr(adapters.asyncio, "sleep", sleep)
    await adapters.stage(
        Connection(),
        CLI(),
        SimpleNamespace(adapter="aruba_2900"),
        SimpleNamespace(version="WC.16.11.0026"),
        "secondary",
        path,
        {},
    )
    assert bytes(captured) == content and log_calls == 3
    assert calls == ["show logging -r", "show flash", "show logging -r", "show flash", "show logging -r"]


@pytest.mark.asyncio
async def test_cx_uses_scp_pull_default_vrf_and_verifies_exact_target_bank(monkeypatch, tmp_path):
    from netrix.core import settings

    monkeypatch.setenv("NETRIX_FIRMWARE_ADVERTISE_HOST", "192.0.2.100")
    settings.cache_clear()
    calls = []

    class CLI:
        async def command(self, value, **kwargs):
            calls.append((value, kwargs))
            return "Secondary Image\nVersion : PL.10.13.1000" if value == "show images" else ""

    await adapters.stage(
        None,
        CLI(),
        SimpleNamespace(adapter="aruba_6100"),
        SimpleNamespace(version="PL.10.13.1000"),
        "secondary",
        tmp_path / "unused",
        {"username": "fw_temp", "password": "temporary", "filename": "random.swi"},
    )
    assert calls[0][0] == "copy scp://fw_temp@192.0.2.100:2222/random.swi secondary vrf default"
    assert calls[0][1]["password"] == "temporary"
    assert calls[1][0] == "show images"
    settings.cache_clear()


@pytest.mark.asyncio
async def test_transfer_protocol_rejection_is_not_hidden_by_later_bank_check():
    terminal = Terminal(
        {"copy fixture\n": ["Download failed with exit code 1: Unsupported protocol.\nswitch# "]}
    )
    cli = adapters.CLI(terminal, "aruba_6100")
    await cli.read()
    with pytest.raises(adapters.FirmwareError) as failure:
        await cli.command("copy fixture", action="transfer")
    assert failure.value.code == "transfer_protocol"


@pytest.mark.asyncio
async def test_hp1950_uses_documented_limited_cli_and_does_not_reboot_during_stage(monkeypatch, tmp_path):
    from netrix.core import settings

    monkeypatch.setenv("NETRIX_FIRMWARE_ADVERTISE_HOST", "192.0.2.100")
    settings.cache_clear()
    calls = []

    class CLI:
        async def command(self, value, **kwargs):
            calls.append(value)
            return (
                "Main startup software images: flash:/1950-system-r3507p10.bin" if value == "summary" else ""
            )

    await adapters.stage(
        None,
        CLI(),
        SimpleNamespace(adapter="hp_1950"),
        SimpleNamespace(version="R3507P10"),
        "main",
        tmp_path / "unused",
        {"filename": "fixture.ipe"},
    )
    assert calls == ["upgrade 192.0.2.100 runtime file fixture.ipe", "summary"]
    assert all("xtd" not in cmd and "reboot" not in cmd for cmd in calls)
    settings.cache_clear()
