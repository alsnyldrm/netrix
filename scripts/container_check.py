"""Explicit Docker smoke test, isolated from production DB, scopes and network."""

import base64
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def wait_until(predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise RuntimeError("Container check timed out")


def main():
    name = "netrix-single-check-" + uuid.uuid4().hex[:8]
    failed = name + "-failed"
    ctl = ("supervisorctl", "-c", "/app/deploy/supervisord.conf")
    with tempfile.TemporaryDirectory(prefix="netrix-container-check-") as directory:
        env = Path(directory) / "env"
        env.write_text(
            "NETRIX_DATABASE_URL=sqlite+pysqlite:////data/test.db\n"
            "NETRIX_REDIS_URL=redis://127.0.0.1:6379/0\n"
            "NETRIX_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(os.urandom(32)).decode() + "\n"
            "NETRIX_SETUP_TOKEN=isolated-container-test-only-token\n"
            "NETRIX_PUBLIC_URL=http://127.0.0.1:8000\n"
        )
        env.chmod(0o600)
        common = [
            "--env-file", str(env), "--network", "none", "--read-only",
            "--tmpfs", "/tmp:size=128m,noexec,nosuid,uid=10001,gid=10001,mode=1777",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--stop-timeout", "60", "--mount", "type=volume,destination=/data",
        ]
        try:
            docker(
                "run", "-d", "--name", name, *common,
                "--health-cmd", "python -m netrix.runtime health",
                "--health-interval", "2s", "--health-timeout", "8s",
                "--health-retries", "2", "--health-start-period", "5s", "netrix:1.1.0",
            )

            def healthy():
                state = json.loads(docker("inspect", name).stdout)[0]["State"]
                if not state["Running"]:
                    raise RuntimeError(f"Candidate stopped with exit code {state['ExitCode']}")
                return docker("exec", name, "python", "-m", "netrix.runtime", "health", check=False).returncode == 0

            wait_until(healthy)
            print("PASS: isolated clean migration, API, Redis, worker, scheduler")
            before = docker("exec", name, *ctl, "pid", "netrix-worker").stdout.strip()
            docker("exec", name, "python", "-c", f"import os, signal; os.kill({int(before)}, signal.SIGKILL)")

            def recovered():
                pid = docker("exec", name, *ctl, "pid", "netrix-worker", check=False).stdout.strip()
                return pid.isdigit() and int(pid) > 0 and pid != before and healthy()

            wait_until(recovered)
            print("PASS: crashed worker is replaced and health recovers")
            docker("exec", name, *ctl, "stop", "netrix-worker")
            assert not healthy(), "Missing worker was incorrectly reported healthy"
            wait_until(lambda: docker("inspect", "-f", "{{.State.Health.Status}}", name).stdout.strip() == "unhealthy")
            docker("exec", name, *ctl, "start", "netrix-worker")
            wait_until(healthy)
            print("PASS: stopped worker fails Docker health; restart restores health")
            docker("exec", name, "redis-cli", "SET", "netrix:test:persistence", "single-container")
            docker("restart", name)
            wait_until(healthy)
            assert docker("exec", name, "redis-cli", "GET", "netrix:test:persistence").stdout.strip() == "single-container"
            docker("exec", name, "redis-cli", "DEL", "netrix:test:persistence")
            print("PASS: full container restart preserves Redis AOF and database schema")
            docker("exec", name, "pip", "check")
            docker("stop", name)
            state = json.loads(docker("inspect", name).stdout)[0]["State"]
            assert state["ExitCode"] == 0 and not state["OOMKilled"], state
            print("PASS: graceful whole-container shutdown")
            # The deliberately unwritable SQLite location fails before Supervisor starts.
            docker(
                "run", "-d", "--name", failed, *common, "-e",
                "NETRIX_DATABASE_URL=sqlite+pysqlite:////nonexistent/database.db", "netrix:1.1.0",
            )
            wait_until(lambda: not json.loads(docker("inspect", failed).stdout)[0]["State"]["Running"])
            state = json.loads(docker("inspect", failed).stdout)[0]["State"]
            assert state["ExitCode"] != 0
            logs = docker("logs", failed).stdout
            assert "spawned:" not in logs
            print("PASS: migration failure exits before any managed service starts")
        except BaseException:
            logs = docker("logs", "--tail", "35", name, check=False)
            print(logs.stdout + logs.stderr)
            raise
        finally:
            for container in (failed, name):
                docker("rm", "-fv", container, check=False)


if __name__ == "__main__":
    main()
