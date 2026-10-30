"""Read-only HP 1950 Comware sessions; capability limits: docs/hp1950-adapter.md."""

import asyncio
import re

import asyncssh

from ..configuration.validation import BackupError
from .aruba import CLI_ERROR, terminal_text

PROMPT = re.compile(r"(?m)^<[^<>\r\n]{1,120}>[ \t\r\n]*\Z")
PAGER = re.compile(r"(?i)-{2,}\s*more\s*-{2,}")
CONFIRM = re.compile(
    r"(?i)(?:switch to extended CLI\s+mode|continue|are you sure)[^\r\n]*\[(?:y/n|yes/no)\]\s*:?\s*\Z"
)
PASSWORD = re.compile(r"(?i)(?:please\s+(?:input|enter)\s+)?password\s*:\s*\Z")
AUTH_ERROR = re.compile(
    r"(?i)(?:wrong|invalid|incorrect)\s+password|password\s+(?:is\s+)?(?:wrong|invalid|incorrect)|authentication\s+fail"
)


async def read_prompt(process, *, prompt=None, limit=256 * 1024, extended=False):
    output, size = "", 0
    pattern = re.compile(r"(?m)^" + re.escape(prompt) + r"[ \t\r\n]*\Z") if prompt else PROMPT
    async with asyncio.timeout(60):
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                raise BackupError("comware_incomplete")
            size += len(chunk.encode())
            if size > limit:
                raise BackupError("too_large")
            output += chunk
            clean = terminal_text(output)
            if PAGER.search(clean):
                raise BackupError("comware_paging")
            if extended:
                for label, extra in (("confirm", CONFIRM), ("password", PASSWORD)):
                    if extra.search(clean):
                        return clean, label
            match = pattern.search(clean)
            if match:
                return clean[: match.start()], match[0].strip()


async def enter_extended(process, prompt, password):
    # Only an explicitly supplied encrypted-profile secret authorizes this session mode.
    if not password or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise BackupError("comware_cli_required")
    process.stdin.write("xtd-cli-mode\n")
    confirmed, supplied = False, False
    for _ in range(3):
        output, state = await read_prompt(process, prompt=prompt, extended=True)
        if CLI_ERROR.search(output) or AUTH_ERROR.search(output):
            raise BackupError("comware_cli_auth")
        if state == "confirm" and not confirmed and not supplied:
            confirmed = True
            process.stdin.write("y\n")
        elif state == "password" and not supplied:
            supplied = True
            process.stdin.write(password + "\n")
        elif state == prompt:
            return
        else:
            raise BackupError("comware_cli_auth")
    raise BackupError("comware_cli_auth")


async def read_comware(connection, *, backup=False, cli_password=""):
    async with connection.create_process(
        term_type="vt100", term_size=(200, 24), stderr=asyncssh.STDOUT
    ) as process:
        _, prompt = await read_prompt(process)

        async def command(value):
            process.stdin.write(value + "\n")
            output, _ = await read_prompt(
                process, prompt=prompt, limit=4 * 1024 * 1024 if backup else 256 * 1024
            )
            lines = output.strip().splitlines()
            if lines and lines[0].strip() in (value, prompt + value, prompt + " " + value):
                lines.pop(0)
            output = "\n".join(lines).strip()
            if CLI_ERROR.search(output):
                raise BackupError("comware_command")
            return output

        # Session-only paging; full CLI is requested only if the saved profile opts in.
        try:
            await command("screen-length disable")
        except BackupError as exc:
            if exc.code != "comware_command":
                raise
            if cli_password:
                await enter_extended(process, prompt, cli_password)
                await command("screen-length disable")
            elif backup:
                raise BackupError("comware_cli_required") from None
            else:
                return await command("summary") + "\n"
        if backup:
            output = await command("display current-configuration")
            validate_comware_config(output)
        else:
            try:
                output = await command("display version")
            except BackupError as exc:
                if exc.code != "comware_command":
                    raise
                output = await command("summary")
        return output + "\n"


def validate_comware_config(output):
    if (
        CLI_ERROR.search(output)
        or PAGER.search(output)
        or not re.search(r"(?m)^\s*version\s+\d+\.\d+", output)
        or not re.search(r"(?m)^\s*sysname\s+\S+", output)
        or not re.search(r"(?m)^#\s*$", output)
        or not re.search(r"(?m)^return\s*\Z", output)
    ):
        raise BackupError("comware_incomplete")
