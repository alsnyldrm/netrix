import io
import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from netrix import backup, core, runtime


@pytest.mark.parametrize("result,expected", [(1, 1), (-15, 143)])
def test_failed_migration_does_not_start_services(monkeypatch, result, expected):
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda args: SimpleNamespace(wait=lambda: result))
    monkeypatch.setattr(runtime.signal, "signal", lambda *args: None)
    monkeypatch.setattr(runtime.os, "execvp", lambda *args: pytest.fail("Services started"))
    assert runtime.start() == expected


def test_successful_migration_executes_supervisor(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda args: SimpleNamespace(wait=lambda: 0))
    monkeypatch.setattr(runtime.signal, "signal", lambda *args: None)
    monkeypatch.setattr(runtime.os, "execvp", lambda *args: calls.append(args))
    runtime.start()
    assert calls == [("supervisord", ["supervisord", "-c", runtime.SUPERVISOR_CONFIG])]


def test_shutdown_during_migration_never_starts_services(monkeypatch):
    handlers, signals = {}, []

    def wait():
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return 0

    migration = SimpleNamespace(wait=wait, poll=lambda: None, send_signal=signals.append)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda args: migration)
    monkeypatch.setattr(runtime.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    monkeypatch.setattr(runtime.os, "execvp", lambda *args: pytest.fail("Services started after shutdown"))
    assert runtime.start() == 143
    assert signals == [signal.SIGTERM]


@pytest.mark.parametrize("fault", [None, "stopped", "missing", "stale", "database"])
def test_container_health_requires_all_processes_and_fresh_heartbeats(monkeypatch, fault):
    processes = [{"name": name, "state": 20} for name in runtime.PROCESSES]
    if fault == "stopped":
        processes[0]["state"] = 0
    proxy = SimpleNamespace(
        supervisor=SimpleNamespace(getAllProcessInfo=lambda: processes),
    )

    class Proxy:
        def __enter__(self):
            return proxy

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(runtime, "ServerProxy", lambda *args, **kwargs: Proxy())
    monkeypatch.setattr(runtime.socket, "setdefaulttimeout", lambda *args: None)
    body = b'{"status":"unavailable"}' if fault == "database" else b'{"status":"ok"}'
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    timestamp = datetime.now(UTC) - timedelta(seconds=100 if fault == "stale" else 0)
    monkeypatch.setattr(core, "redis_client", lambda: SimpleNamespace(
        get=lambda key: None if fault == "missing" else timestamp.isoformat(),
    ))
    if fault:
        with pytest.raises(RuntimeError):
            runtime.health()
    else:
        runtime.health()


def test_backup_uses_private_client_file_without_secret_arguments(monkeypatch):
    monkeypatch.setenv("NETRIX_DATABASE_URL", "mysql+pymysql://netrix:test%21%22%5C%0A@10.2.0.31/netrix")
    observed = []

    def run(command, **kwargs):
        client = Path(command[1].split("=", 1)[1])
        observed.append(client)
        assert client.stat().st_mode & 0o777 == 0o600
        assert 'password="test!\\"\\\\\\n"' in client.read_text()
        assert command[0] == "mariadb-dump"
        assert command[-1] == "netrix"
        assert "--single-transaction" in command
        assert all("test!" not in arg for arg in command)

    monkeypatch.setattr(backup.subprocess, "run", run)
    backup.run()
    assert observed and not observed[0].exists()


def test_restore_requires_confirmation_before_client_execution(monkeypatch):
    monkeypatch.setenv("NETRIX_DATABASE_URL", "mysql+pymysql://netrix:test-only@10.2.0.31/netrix")
    monkeypatch.setattr(backup.subprocess, "run", lambda *args, **kwargs: pytest.fail("Restore executed"))
    with pytest.raises(ValueError, match="confirmation"):
        backup.run(restore=True, confirm_database="wrong")


def test_restore_uses_existing_container_client(monkeypatch):
    monkeypatch.setenv("NETRIX_DATABASE_URL", "mysql+pymysql://netrix:test-only@10.2.0.31/netrix")
    observed = []
    monkeypatch.setattr(backup.subprocess, "run", lambda command, **kwargs: observed.append(command))
    backup.run(restore=True, confirm_database="netrix")
    assert observed[0][0] == "mariadb"
    assert observed[0][-1] == "netrix"
    assert len(observed[0]) == 3
