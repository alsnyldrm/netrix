"""Bounded fake CLI streams reproduce AOS-S login gating; never access real networks."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from netrix.access import runtime


class Switch:
    def __init__(self, banner=True, reject_paging=False):
        self.stdout = self
        self.stdin = self
        self.queue = asyncio.Queue()
        self.writes = []
        self.reject_paging = reject_paging
        self.queue.put_nowait("Welcome\r\nPress any key to continue" if banner else "SW-01# ")

    async def read(self, size):
        return await self.queue.get()

    def write(self, value):
        self.writes.append(value)
        if value == " ":
            self.queue.put_nowait("\r\n\x1b[32mSW-01#\x1b[0m ")
        elif value.strip() == "no page":
            self.queue.put_nowait(("% Invalid input\r\n" if self.reject_paging else "") + "SW-01# ")
        elif value.strip() == "hang":
            self.queue.put_nowait("partial requested output\r\n")
        elif value.strip() == "needs-confirmation":
            self.queue.put_nowait("Continue [y/n]: ")
        else:
            self.queue.put_nowait(value + "VERSION WC.16.11\r\nSW-01# ")

    async def drain(self):
        pass


def mock_connect(monkeypatch, process):
    @asynccontextmanager
    async def create_process(**kwargs):
        yield process

    @asynccontextmanager
    async def connect(*args):
        yield SimpleNamespace(create_process=create_process)

    monkeypatch.setattr(runtime, "connect", connect)


@pytest.mark.asyncio
async def test_aoss_login_gate_and_session_paging_before_command(monkeypatch):
    process = Switch()
    mock_connect(monkeypatch, process)
    async with asyncio.timeout(0.25):
        output, success = await runtime.run_command(
            SimpleNamespace(adapter="aruba_2900"), {"initial_command": ""}, "show version"
        )
    assert success and "VERSION WC.16.11" in output
    assert process.writes == [" ", "no page\n", "show version\n"]


@pytest.mark.asyncio
async def test_initial_command_and_confirmation_are_not_replayed(monkeypatch):
    process = Switch()
    mock_connect(monkeypatch, process)
    output, success = await runtime.run_command(
        SimpleNamespace(adapter="aruba_2900"), {"initial_command": "show clock"}, "show version"
    )
    assert (
        success and process.writes.count("show clock\n") == 1 and process.writes.count("show version\n") == 1
    )
    process = Switch(banner=False)
    mock_connect(monkeypatch, process)
    with pytest.raises(ValueError, match="interactive_prompt"):
        await runtime.run_command(SimpleNamespace(adapter="aruba_2900"), {}, "needs-confirmation")
    assert "y\n" not in process.writes


@pytest.mark.asyncio
async def test_paging_rejection_stops_before_user_command(monkeypatch):
    process = Switch(reject_paging=True)
    mock_connect(monkeypatch, process)
    progress = {}
    with pytest.raises(ValueError, match="paging_setup"):
        await runtime.run_command(SimpleNamespace(adapter="aruba_2900"), {}, "show version", progress)
    assert "show version\n" not in process.writes
    assert not progress["command_sent"]


@pytest.mark.asyncio
async def test_partial_requested_output_survives_timeout(monkeypatch):
    process = Switch()
    mock_connect(monkeypatch, process)
    progress = {}
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await runtime.run_command(SimpleNamespace(adapter="aruba_2900"), {}, "hang", progress)
    assert progress["phase"] == "command" and progress["command_sent"]
    assert "partial requested output" in progress["partial"]
    assert process.writes.count("hang\n") == 1


@pytest.mark.asyncio
async def test_configured_paging_initial_command_runs_once(monkeypatch):
    process = Switch()
    mock_connect(monkeypatch, process)
    output, success = await runtime.run_command(
        SimpleNamespace(adapter="aruba_2900"), {"initial_command": "no page"}, "show version"
    )
    assert success and process.writes == [" ", "no page\n", "show version\n"]


@pytest.mark.asyncio
async def test_timeout_stage_and_partial_failures_share_total_output_limit(monkeypatch):
    class Client:
        async def get(self, key):
            return None

    async def store(*args, **kwargs):
        pass

    async def fail(device, profile, command, progress):
        if device == "0":
            progress.update(phase="connection", command_sent=False)
        else:
            progress.update(phase="command", command_sent=True, partial="partial result " + "x" * 65500)
        raise TimeoutError()

    monkeypatch.setattr(runtime, "state", store)
    monkeypatch.setattr(runtime, "target_state", store)
    monkeypatch.setattr(runtime, "connection_data", lambda value, id: (id, {}))
    monkeypatch.setattr(runtime, "run_command", fail)
    value = {
        "command": "show version",
        "timeout": 5,
        "targets": [{"device_id": str(n), "status": "queued", "output": ""} for n in range(40)],
    }
    await runtime.run_batch(Client(), "fixture", value)
    assert not value["targets"][0]["command_sent"]
    assert "gönderilmedi" in value["targets"][0]["error"]
    assert value["targets"][1]["command_sent"] and "partial result" in value["targets"][1]["output"]
    assert all(t["status"] == "failed" for t in value["targets"])
    assert sum(len(t["output"].encode()) for t in value["targets"]) < 2 * 1024 * 1024 + 4000
