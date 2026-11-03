"""Interactive session logout and idle deadlines, without network or real waiting."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from netrix.access import ephemeral as e
from netrix.access import runtime


class Shell:
    def __init__(self, responds=True):
        self.stdin = self.stdout = self
        self.writes = []
        self.output = asyncio.Queue()
        self.ended = asyncio.Event()
        self.responds = responds
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        if data == "exit\n" and self.responds:
            self.ended.set()

    async def drain(self):
        pass

    async def read(self, size):
        return await self.output.get()

    def change_terminal_size(self, *args):
        pass

    async def wait_closed(self):
        await self.ended.wait()

    def close(self):
        self.closed = True
        self.ended.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cancel", "idle", "viewer", "shutdown", "revoked", "eof"])
async def test_session_shutdown_sends_exit_and_closes_transport(monkeypatch, reason):
    clock = SimpleNamespace(stamp=0.0)
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: clock.stamp, time=lambda: 0))
    monkeypatch.setattr(e, "unpack", lambda value: value)
    shell = Shell()
    ready = asyncio.Event()
    polled = asyncio.Event()
    inbox = asyncio.Queue()
    connection_closed = []

    class Client:
        cancel = False

        async def get(self, key):
            polled.set()
            if key == e.key("cancel", "test"):
                return "1" if self.cancel else None
            return None if reason == "viewer" else "present"

        async def xread(self, *args, **kwargs):
            return await inbox.get()

        async def xdel(self, *args):
            pass

    @asynccontextmanager
    async def process(**kwargs):
        try:
            yield shell
        finally:
            shell.close()

    @asynccontextmanager
    async def connect(*args):
        try:
            yield SimpleNamespace(create_process=process)
        finally:
            connection_closed.append(True)

    async def store(*args, **kwargs):
        ready.set()

    monkeypatch.setattr(runtime, "connect", connect)
    monkeypatch.setattr(runtime, "state", store)
    monkeypatch.setattr(runtime, "event", store)
    validations = []

    def connection_data(*args):
        validations.append(True)
        if reason == "revoked" and len(validations) > 1:
            raise HTTPException(403, "Oturum veya yetki sona erdi")
        return None, {"idle_timeout_minutes": 1}

    monkeypatch.setattr(runtime, "connection_data", connection_data)
    client = Client()
    task = asyncio.create_task(
        runtime.shell_session(client, "test", {"device_id": "device", "cols": 80, "rows": 24, "created": 0})
    )
    await ready.wait()
    await asyncio.sleep(0)
    if reason == "idle":
        # Actual user input resets the timer; resize and remote output don't.
        clock.stamp = 50
        await inbox.put([("in", [("1-0", {"data": {"type": "input", "data": "show"}})])])
        while not shell.writes:
            await asyncio.sleep(0)
        clock.stamp = 100
        await polled.wait()
        assert not task.done(), "Input at t=50 should postpone the original t=60 deadline"
        clock.stamp = 110
        await inbox.put([("in", [("2-0", {"data": {"type": "resize", "cols": 100, "rows": 30}})])])
        await shell.output.put("continuous device output")
    elif reason == "viewer":
        clock.stamp = 61
    elif reason == "shutdown":
        task.cancel()
    elif reason == "revoked":
        clock.stamp = 10
    elif reason == "eof":
        await shell.output.put("")
    else:
        client.cancel = True
    if reason == "eof":
        await asyncio.wait_for(task, 3)
        assert not shell.writes, "A device which already logged out needs no exit"
    else:
        with pytest.raises((runtime.SessionEnded, asyncio.CancelledError, HTTPException)):
            await asyncio.wait_for(task, 3)
        assert shell.writes[-2:] == ["\x03\x15", "exit\n"]
        assert shell.writes.count("exit\n") == 1
    assert shell.closed and connection_closed


@pytest.mark.asyncio
async def test_logout_of_unresponsive_or_broken_device_is_bounded():
    shell = Shell(responds=False)
    await asyncio.wait_for(runtime.logout(shell, timeout=0.02), 0.2)
    assert shell.writes == ["\x03\x15", "exit\n"] and shell.closed

    def broken(data):
        raise BrokenPipeError()

    shell = Shell()
    shell.write = broken
    await runtime.logout(shell, timeout=0.02)
    assert shell.closed
