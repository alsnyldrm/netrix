"""Read-only, short-lived SFTP/TFTP grants for explicitly running firmware jobs."""

import asyncio
import os
import secrets
import struct
from datetime import timedelta
from pathlib import Path

import asyncssh
from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory, settings
from ..identity.security import token_hash
from .limits import MAX_CONCURRENCY, MAX_TRANSFER_CONNECTIONS
from .service import image_path

connections = {}
pending_connections = set()


def grant(target_id, protocol):
    password = secrets.token_urlsafe(24)
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, target_id)
        image = db.get(m.FirmwareImage, row.image_id)
        secure = protocol in ("sftp", "scp")
        row.transfer_username = "fw_" + secrets.token_hex(10) if secure else None
        row.transfer_secret_hash = token_hash(password) if secure else ""
        row.transfer_name = (
            "netrix-fw-" + secrets.token_hex(24) + (".ipe" if image.family == "hp1950" else ".swi")
        )
        row.transfer_expires_at = now() + timedelta(minutes=45)
        db.commit()
        return row.transfer_username, password, row.transfer_name


def lookup(peer, *, username=None, filename=None):
    with session_factory()() as db:
        condition = (
            m.FirmwareTarget.transfer_username == username
            if username
            else m.FirmwareTarget.transfer_name == filename
        )
        row = db.scalar(
            select(m.FirmwareTarget).where(
                condition,
                m.FirmwareTarget.status == "running",
                m.FirmwareTarget.phase == "transferring",
                m.FirmwareTarget.transfer_expires_at > now(),
            )
        )
        if not row:
            return None
        device = db.get(m.Device, row.device_id)
        if not device or device.management_ip != peer or device.archived:
            return None
        image = db.get(m.FirmwareImage, row.image_id)
        if filename and filename != row.transfer_name:
            return None
        return {
            "id": row.id,
            "path": image_path(image),
            "filename": row.transfer_name,
            "hash": row.transfer_secret_hash,
            "expires": row.transfer_expires_at,
            "size": image.size_bytes,
        }


def record_bytes(target_id, size):
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, target_id)
        if row:
            row.transfer_bytes = max(row.transfer_bytes, size)
            db.commit()


def revoke(target_id):
    with session_factory()() as db:
        row = db.get(m.FirmwareTarget, target_id)
        if row:
            for connection in connections.pop(row.transfer_name, set()):
                connection.close()
            row.transfer_expires_at, row.transfer_secret_hash = now(), ""
            db.commit()


def host_key():
    path = Path(settings().firmware_directory) / "sftp_host_key"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        key = asyncssh.generate_private_key("ssh-ed25519")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(key.export_private_key())
        except FileExistsError:
            pass
    return asyncssh.read_private_key(path)


async def start_ssh(host, port):
    return await asyncssh.create_server(
        TransferSSH,
        host,
        port,
        server_host_keys=[host_key()],
        sftp_factory=TransferSFTP,
        login_timeout=15,
        password_auth=True,
        public_key_auth=False,
        allow_scp=True,
        sftp_version=3,
    )


class TransferSSH(asyncssh.SSHServer):
    def connection_made(self, connection):
        self.connection = connection
        self.access = None
        if len(pending_connections) >= MAX_TRANSFER_CONNECTIONS:
            connection.close()
        else:
            pending_connections.add(connection)

    def connection_lost(self, exc):
        pending_connections.discard(self.connection)
        if self.access:
            sessions = connections.get(self.access["filename"])
            if sessions:
                sessions.discard(self.connection)
                if not sessions:
                    connections.pop(self.access["filename"], None)

    def begin_auth(self, username):
        peer = self.connection.get_extra_info("peername")[0]
        self.access = lookup(peer, username=username)
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        if self.access and secrets.compare_digest(self.access["hash"], token_hash(password)):
            self.connection.set_extra_info(firmware_access=self.access)
            connections.setdefault(self.access["filename"], set()).add(self.connection)
            return True
        return False


class TransferSFTP(asyncssh.SFTPServer):
    def __init__(self, channel):
        super().__init__(channel)
        self.access = channel.get_connection().get_extra_info("firmware_access")

    def permitted(self, path):
        if not self.access or now() >= self.access["expires"]:
            raise asyncssh.SFTPPermissionDenied("Transfer expired")
        if path not in (self.access["filename"].encode(), b"/" + self.access["filename"].encode()):
            raise asyncssh.SFTPPermissionDenied("File unavailable")

    def map_path(self, path):
        self.permitted(path)
        return os.fsencode(self.access["path"])

    def realpath(self, path, *args):
        if path in (b"", b".", b"/"):
            return b"/"
        self.permitted(path)
        return b"/" + self.access["filename"].encode()

    def open(self, path, pflags, attrs):
        self.permitted(path)
        if pflags != asyncssh.FXF_READ:
            raise asyncssh.SFTPPermissionDenied("Read only")
        return open(self.access["path"], "rb")

    def read(self, file_obj, offset, size):
        if now() >= self.access["expires"]:
            raise asyncssh.SFTPPermissionDenied("Transfer expired")
        return super().read(file_obj, offset, min(size, 1024 * 1024))

    def close(self, file_obj):
        record_bytes(self.access["id"], file_obj.tell())
        file_obj.close()

    def deny(self, *args, **kwargs):
        raise asyncssh.SFTPPermissionDenied("Read only")

    write = remove = mkdir = rmdir = rename = posix_rename = setstat = fsetstat = symlink = link = deny
    scandir = readlink = statvfs = fstatvfs = lsetstat = deny


class AckProtocol(asyncio.DatagramProtocol):
    def __init__(self, peer):
        self.peer = peer
        self.queue = asyncio.Queue(maxsize=8)

    def datagram_received(self, data, addr):
        if addr == self.peer and not self.queue.full():
            self.queue.put_nowait(data)


def rrq(data):
    if len(data) > 512 or data[:2] != b"\x00\x01" or not data.endswith(b"\x00"):
        raise ValueError("Invalid RRQ")
    parts = data[2:-1].split(b"\x00")
    if len(parts) < 2 or parts[1].lower() != b"octet" or len(parts) % 2:
        raise ValueError("Binary mode required")
    filename = parts[0].decode("ascii")
    if not __import__("re").fullmatch(r"netrix-fw-[a-f0-9]{48}\.ipe", filename):
        raise ValueError("Invalid filename")
    options = {}
    for key, value in zip(parts[2::2], parts[3::2], strict=True):
        key = key.decode("ascii").lower()
        number = int(value)
        if key == "blksize" and 8 <= number <= 65464:
            options[key] = min(number, 1468)
        elif key == "tsize" and number == 0:
            options[key] = 0
        elif key == "timeout" and 1 <= number <= 5:
            options[key] = number
    return filename, options


class TFTP(asyncio.DatagramProtocol):
    def __init__(self):
        self.active = {}
        self.ports = set(
            range(settings().firmware_transfer_port_start, settings().firmware_transfer_port_start + 16)
        )

    def datagram_received(self, data, addr):
        if addr in self.active or len(self.active) >= MAX_CONCURRENCY:
            return
        try:
            filename, options = rrq(data)
            access = lookup(addr[0], filename=filename)
            if not access or access["hash"] or not self.ports:
                return
        except (ValueError, UnicodeError):
            return
        port = min(self.ports)
        self.ports.remove(port)
        task = asyncio.create_task(self.send(addr, access, options, port))
        self.active[addr] = task

        def done(future):
            self.active.pop(addr, None)
            self.ports.add(port)
            if not future.cancelled():
                future.exception()  # No device data or temporary transfer names in logs.

        task.add_done_callback(done)

    async def send(self, peer, access, options, port):
        protocol = AckProtocol(peer)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: protocol, local_addr=("0.0.0.0", port)
        )
        block_size = options.get("blksize", 512)

        async def exchange(packet, block):
            for _ in range(5):
                transport.sendto(packet, peer)
                try:
                    async with asyncio.timeout(options.get("timeout", 2)):
                        while True:
                            answer = await protocol.queue.get()
                            if answer == struct.pack("!HH", 4, block):
                                return
                            if answer[:2] == b"\x00\x05":
                                raise ValueError("Client error")
                except TimeoutError:
                    pass
            raise TimeoutError()

        try:
            async with asyncio.timeout(1800):
                if options:
                    if "tsize" in options:
                        options["tsize"] = access["size"]
                    packet = b"\x00\x06" + b"".join(
                        k.encode() + b"\x00" + str(v).encode() + b"\x00" for k, v in options.items()
                    )
                    await exchange(packet, 0)
                total, number = 0, 1
                with access["path"].open("rb") as source:
                    while now() < access["expires"]:
                        chunk = source.read(block_size)
                        await exchange(struct.pack("!HH", 3, number) + chunk, number)
                        total += len(chunk)
                        number = (number + 1) % 65536
                        if len(chunk) < block_size:
                            record_bytes(access["id"], total)
                            return
                    raise TimeoutError()
        finally:
            transport.close()

    def connection_lost(self, exc):
        for task in self.active.values():
            task.cancel()
