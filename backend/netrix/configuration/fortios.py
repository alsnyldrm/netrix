"""Fortinet's native sys_config export over SCP on an existing SSH connection."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import asyncssh

from .validation import MAX_CONFIG_BYTES, BackupError, validate_fortios_backup


async def fetch_fortios_backup(connection):
    def progress(source, destination, received, total):
        if total > MAX_CONFIG_BYTES or received > MAX_CONFIG_BYTES:
            raise BackupError("too_large")

    # 0700 directory + 0600 file. Production /tmp is tmpfs; cleanup also runs on
    # failure/cancellation. Never use a remote filename as a local destination.
    with TemporaryDirectory(prefix="netrix-backup-") as directory:
        path = Path(directory) / "sys_config"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            await asyncssh.scp(
                (connection, "sys_config"),
                path,
                preserve=False,
                recurse=False,
                block_size=64 * 1024,
                progress_handler=progress,
            )
        except asyncssh.Error:
            raise BackupError("scp_failed") from None
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise BackupError("too_large")
        try:
            content = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise BackupError("invalid_fortios") from None
        validate_fortios_backup(content)
        return content
