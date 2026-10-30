"""Single-container startup and a health probe covering all application processes."""

import argparse
import json
import os
import signal
import socket
import subprocess
import urllib.request
from datetime import UTC, datetime
from xmlrpc.client import ServerProxy

SUPERVISOR_CONFIG = "/app/deploy/supervisord.conf"
PROCESSES = {"netrix-api", "netrix-redis", "netrix-worker", "netrix-scheduler", "netrix-tests"}


def start():
    # Migrations only need the external database. No service is exposed before success.
    migration = subprocess.Popen(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"])
    interrupted = 0

    def terminate(signum, frame):
        nonlocal interrupted
        interrupted = signum
        if migration.poll() is None:
            migration.send_signal(signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, terminate)
    result = migration.wait()
    if interrupted:
        return 128 + interrupted
    if result:
        return result if result > 0 else 128 - result
    os.execvp("supervisord", ["supervisord", "-c", SUPERVISOR_CONFIG])


def health():
    from supervisor.xmlrpc import SupervisorTransport

    from .core import redis_client

    socket.setdefaulttimeout(3)
    transport = SupervisorTransport(None, None, "unix:///tmp/netrix-supervisor.sock")
    with ServerProxy("http://localhost", transport=transport) as server:
        processes = server.supervisor.getAllProcessInfo()
    running = {item["name"] for item in processes if item["state"] == 20}
    if running != PROCESSES:
        raise RuntimeError("A required NETRIX process is not running")
    with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/ready", timeout=3) as response:
        if json.load(response).get("status") != "ok":
            raise RuntimeError("NETRIX dependencies are unavailable")
    for role in ("worker", "scheduler", "tests"):
        value = redis_client().get(f"netrix:{role}:heartbeat")
        if not value:
            raise RuntimeError("A NETRIX process has no heartbeat")
        age = (datetime.now(UTC) - datetime.fromisoformat(value)).total_seconds()
        if not -5 <= age < 90:
            raise RuntimeError("A NETRIX process heartbeat is stale")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "health"])
    args = parser.parse_args()
    if args.action == "start":
        return start()
    try:
        health()
    except Exception as exc:
        # Health logs must never include connection URLs or credentials.
        print(f"NETRIX unhealthy: {type(exc).__name__}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
