"""Explicit loopback SCP/SFTP/TFTP integration; temporary DB and fixture bytes only."""

import asyncio
import hashlib
import os
import secrets
import socket
import struct
import tempfile
from datetime import timedelta
from pathlib import Path

import asyncssh
from cryptography.fernet import Fernet


async def main():
    with tempfile.TemporaryDirectory(prefix="netrix-transfer-check-") as directory:
        os.environ.update(
            NETRIX_DATABASE_URL="sqlite+pysqlite:///" + directory + "/test.db",
            NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            NETRIX_FIRMWARE_DIRECTORY=directory,
            NETRIX_FIRMWARE_TRANSFER_PORT_START="20780",
        )
        from netrix import models as m
        from netrix.core import Base, engine, now, session_factory, settings
        from netrix.firmware import transfers
        from netrix.firmware.service import image_path
        from netrix.identity.security import token_hash

        settings.cache_clear()
        engine.cache_clear()
        Base.metadata.create_all(engine())
        content = secrets.token_bytes(120001)
        username, password, name = (
            "fw_fixture",
            secrets.token_urlsafe(24),
            "netrix-fw-" + secrets.token_hex(24) + ".ipe",
        )
        with session_factory()() as db:
            from netrix.inventory.device_types import seed_defaults

            seed_defaults(db)
            vrf = m.VRF(name="Fixture")
            db.add(vrf)
            db.flush()
            device = m.Device(name="Loopback fixture", management_ip="127.0.0.1", vrf_id=vrf.id)
            image = m.FirmwareImage(
                name="Fixture",
                family="hp1950",
                version="R3507P10",
                models=["JG960A"],
                original_name="fixture.ipe",
                expected_sha256=hashlib.sha256(content).hexdigest(),
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                status="ready",
            )
            plan = m.FirmwarePlan(name="Loopback only", steps=[], status="running")
            db.add_all([device, image, plan])
            db.flush()
            image_path(image).write_bytes(content)
            target = m.FirmwareTarget(
                plan_id=plan.id,
                device_id=device.id,
                image_id=image.id,
                stage=0,
                status="running",
                phase="transferring",
                transfer_username=username,
                transfer_secret_hash=token_hash(password),
                transfer_name=name,
                transfer_expires_at=now() + timedelta(minutes=3),
            )
            db.add(target)
            db.commit()
            target_id = target.id
        key = transfers.host_key()
        server = await transfers.start_ssh("127.0.0.1", 0)
        port = server.get_port()
        known = Path(directory) / "known_hosts"
        known.write_bytes(f"[127.0.0.1]:{port} ".encode() + key.export_public_key())
        try:
            async with asyncssh.connect(
                "127.0.0.1",
                port=port,
                username=username,
                password=password,
                known_hosts=str(known),
                client_keys=[],
            ) as connection:
                downloaded = Path(directory) / "scp-readback.bin"
                await asyncssh.scp((connection, name), downloaded)
                assert downloaded.read_bytes() == content
                for wrong in ("../fixture.ipe", "/etc/passwd", name + ";id"):
                    try:
                        await asyncssh.scp((connection, wrong), downloaded)
                        raise AssertionError("SCP traversal/command accepted")
                    except asyncssh.Error:
                        pass
                try:
                    await asyncssh.scp(downloaded, (connection, name))
                    raise AssertionError("SCP upload accepted")
                except asyncssh.Error:
                    pass
                assert downloaded.read_bytes() == content
                assert image_path(image).read_bytes() == content
                async with connection.start_sftp_client() as client:
                    async with client.open(name, "rb") as source:
                        assert await source.read() == content
                    for wrong in ("../fixture.ipe", "/etc/passwd"):
                        try:
                            await client.open(wrong, "rb")
                            raise AssertionError("Traversal accepted")
                        except asyncssh.SFTPPermissionDenied:
                            pass
                    try:
                        await client.remove(name)
                        raise AssertionError("Delete accepted")
                    except asyncssh.SFTPPermissionDenied:
                        pass
                try:
                    await connection.run("id", check=True)
                    raise AssertionError("Shell execution accepted")
                except asyncssh.ChannelOpenError:
                    pass
            try:
                async with asyncssh.connect(
                    "127.0.0.1",
                    port=port,
                    username=username,
                    password="wrong",
                    known_hosts=str(known),
                    client_keys=[],
                ):
                    raise AssertionError("Wrong password accepted")
            except asyncssh.PermissionDenied:
                pass
            print(
                "PASS: actual loopback SCP/SFTP, pinned host key, binary readback, traversal/upload/delete/shell denial and bad password"
            )
            with session_factory()() as db:
                row = db.get(m.FirmwareTarget, target_id)
                row.transfer_secret_hash = ""
                row.transfer_username = None
                db.commit()
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                transfers.TFTP, local_addr=("127.0.0.1", 0)
            )
            tftp_port = transport.get_extra_info("sockname")[1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            sock.bind(("127.0.0.1", 0))
            loop = asyncio.get_running_loop()
            try:
                sock.sendto(
                    b"\x00\x01" + name.encode() + b"\x00octet\x00blksize\x001468\x00tsize\x000\x00",
                    ("127.0.0.1", tftp_port),
                )
                answer, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), 3)
                assert answer.startswith(b"\x00\x06") and str(len(content)).encode() in answer
                sock.sendto(b"\x00\x04\x00\x00", peer)
                received = bytearray()
                block = 1
                while True:
                    answer, address = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), 3)
                    assert address == peer and answer[:4] == struct.pack("!HH", 3, block)
                    received.extend(answer[4:])
                    sock.sendto(struct.pack("!HH", 4, block), peer)
                    if len(answer) < 1472:
                        break
                    block += 1
                assert bytes(received) == content, (
                    len(received),
                    len(content),
                    block,
                    len(answer),
                    answer[:4].hex(),
                )
                await asyncio.sleep(0.1)
                transfers.revoke(target_id)
                sock.sendto(b"\x00\x01" + name.encode() + b"\x00octet\x00", ("127.0.0.1", tftp_port))
                try:
                    await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), 0.2)
                    raise AssertionError("Expired grant served")
                except TimeoutError:
                    pass
                print(
                    "PASS: actual loopback TFTP, option negotiation, exact binary readback and revoked grant denial"
                )
            finally:
                sock.close()
                transport.close()
        finally:
            server.close()
            await server.wait_closed()
            engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
