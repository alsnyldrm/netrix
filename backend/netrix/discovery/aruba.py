"""Read-only Aruba CLI sessions. Commands and sources: docs/aruba-adapters.md."""

import asyncio
import re

import asyncssh

from ..configuration.validation import BackupError

ARUBA_ADAPTERS = {
    "aruba_5400": ("no page", "show modules"),
    "aruba_2900": ("no page", "show modules"),
    "aruba_6100": ("no page", "show system"),
    "aruba_7200": ("no paging", "show version"),
}
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
PROMPT = re.compile(r"(?m)^(?:[\w.:-]+(?:\([^\r\n()]*\))?|\([^\r\n()]+\)(?:\s*\[[^\r\n\]]+\])?)\s*[#>]\s*\Z")
CLI_ERROR = re.compile(
    r"(?im)^\s*(?:%\s*)?(?:invalid (?:input|command)|unknown command|"
    r"unrecognized command|incomplete command|permission denied|access denied|"
    r"authorization failed|not authorized|command not found)\b|--\s*more\s*--"
)


def terminal_text(text):
    # AOS-S redraws the first terminal column instead of emitting CRLF. Keep
    # that boundary before dropping cursor controls, or echo and prompt join.
    text = re.sub(r"\x1b\[(?:\d*;)?[01]?[Hf]", "\n", text)
    text = ANSI.sub("", text).replace("\r", "").replace("\x00", "")
    # Backspace is used by some switch banners and terminal redraws.
    while "\b" in text:
        text = re.sub(r"[^\n\b]\x08|^\x08", "", text, flags=re.M)
        if "\b" in text:
            text = text.replace("\b", "")
    return text


async def read_prompt(process, *, prompt=None, limit=256 * 1024):
    output, size, continued = "", 0, False
    pattern = re.compile(r"(?m)^" + re.escape(prompt) + r"[ \t\r\n]*\Z") if prompt else PROMPT
    async with asyncio.timeout(60):
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                raise BackupError("aruba_incomplete")
            size += len(chunk.encode())
            if size > limit:
                raise BackupError("too_large")
            output += chunk
            clean = terminal_text(output)
            if not prompt and not continued and re.search(r"press any key to continue", clean, re.I):
                process.stdin.write(" ")
                continued = True
            match = pattern.search(clean)
            if match:
                return clean[: match.start()], match[0].strip()


async def read_aruba(connection, adapter, *, backup=False):
    paging, identity = ARUBA_ADAPTERS[adapter]
    # A single PTY shell preserves the session-only paging setting. Many AOS-S
    # versions do not support SSH exec channels. No enable/configure/write commands.
    async with connection.create_process(
        term_type="vt100", term_size=(200, 24), stderr=asyncssh.STDOUT
    ) as process:
        _, prompt = await read_prompt(process)
        if not prompt.endswith("#"):
            raise BackupError("aruba_privilege")
        command = "show running-config" if backup else identity
        for current in (paging, command):
            process.stdin.write(current + "\n")
            output, _ = await read_prompt(
                process, prompt=prompt, limit=4 * 1024 * 1024 if backup else 256 * 1024
            )
            lines = output.strip().splitlines()
            if lines and lines[0].strip() in (current, prompt + current, prompt + " " + current):
                lines.pop(0)
            output = "\n".join(lines).strip()
            if CLI_ERROR.search(output):
                raise BackupError("aruba_command")
        if backup:
            validate_aruba_config(adapter, output)
        return output + "\n"


def validate_aruba_config(adapter, output):
    # Require device config structure, not just a nonempty CLI response.
    marker = (
        r"(?im)^;[^\n]*Configuration Editor;[^\n]*Created on release"
        if adapter in ("aruba_5400", "aruba_2900")
        else r"(?im)^(?:!\s*)?version\s+\S+"
    )
    if (
        CLI_ERROR.search(output)
        or not re.search(marker, output)
        or not re.search(r"(?m)^hostname\s+\S+", output)
    ):
        raise BackupError("aruba_incomplete")
