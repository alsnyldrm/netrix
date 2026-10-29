"""Real SSH handshakes against an ephemeral loopback fixture; never queries a device."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import asyncssh
from netrix.core import settings
from netrix.discovery.connection_tests import probe
from netrix.discovery.protocols import fetch_config, fetch_identity


class Server(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == "fixture" and password == "fixture-password"


async def process(session):
    if session.command == "get system status":
        session.stdout.write("Version: FortiGate-600F v7.0.0\n")
    else:
        session.stdout.write("fixture-config\n")
    session.exit(0)


async def check():
    with TemporaryDirectory() as temporary:
        known = Path(temporary) / "known_hosts"
        known.write_text("")
        os.environ["NETRIX_KNOWN_HOSTS"] = str(known)
        settings.cache_clear()
        key = asyncssh.generate_private_key("ssh-ed25519")
        async with await asyncssh.create_server(
            Server, "127.0.0.1", 0, server_host_keys=[key], process_factory=process
        ) as server:
            device = SimpleNamespace(
                management_ip="127.0.0.1",
                config_port=server.get_port(),
                adapter="fortios",
                ssh_trust_host_key=False,
            )
            secret = {"username": "fixture", "password": "fixture-password"}
            for action in (
                lambda: probe(device, "ssh", secret, None),
                lambda: fetch_identity(device, secret),
                lambda: fetch_config(device, secret),
            ):
                try:
                    await action()
                except asyncssh.HostKeyNotVerifiable:
                    pass
                else:
                    raise AssertionError("Unknown host key must be rejected by default")
            device.ssh_trust_host_key = True
            assert "Anahtara güven" in await probe(device, "ssh", secret, None)
            assert (await fetch_identity(device, secret))["model"] == "FortiGate-600F"
            assert (await fetch_config(device, secret)).strip() == "fixture-config"
            try:
                await probe(device, "ssh", {**secret, "password": "wrong-fixture"}, None)
            except asyncssh.PermissionDenied:
                pass
            else:
                raise AssertionError("Trusting a host must not bypass user authentication")
            device.ssh_trust_host_key = False
            known.write_text(f"[127.0.0.1]:{server.get_port()} " + key.export_public_key().decode())
            assert "başarılı" in await probe(device, "ssh", secret, None)
    print(
        "SSH loopback PASS: unknown host rejected; explicit trust supports test/identity/backup; password verified; known host accepted"
    )


asyncio.run(check())
