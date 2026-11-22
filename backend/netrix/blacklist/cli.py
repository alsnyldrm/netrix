"""Bounded SSH shell for configuration modes, using the saved NETRIX trust policy."""

import asyncio
import re
from contextlib import asynccontextmanager

import asyncssh

from ..discovery.aruba import CLI_ERROR, terminal_text
from ..discovery.comware import enter_extended
from ..discovery.protocols import ssh_known_hosts

CONFIG_PROMPT = re.compile(
    r"(?m)^(?:[\w.:-]+(?:\([^\r\n()]*\))?"
    r"|\([^()\r\n]+\)(?:\s*\[[^\]\r\n]+\])?(?:\s*\([^()\r\n]+\))?)\s*[#>]\s*\Z"
)
HP_CONFIG_PROMPT = re.compile(r"(?m)^(?:<[^<>\r\n]+>|\[[^\[\]\r\n]+\])[ \t\r\n]*\Z")


class ACLError(ValueError):
    pass


class Shell:
    def __init__(self, process, adapter):
        self.process = process
        self.adapter = adapter

    async def read(self, *, save=False):
        chunks, size, answered = [], 0, False
        pattern = HP_CONFIG_PROMPT if self.adapter == "hp_1950" else CONFIG_PROMPT
        async with asyncio.timeout(45):
            while True:
                chunk = await self.process.stdout.read(8192)
                if not chunk:
                    raise ACLError("SSH oturumu tamamlanmadan kapandı; yeniden göndererek sonucu doğrulayın.")
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ACLError("Cihaz yanıtı boyut sınırını aştı.")
                chunks.append(chunk)
                clean = terminal_text("".join(chunks))
                if re.search(r"press any key to continue", clean, re.I) and not answered:
                    self.process.stdin.write(" ")
                    answered = True
                if save and re.search(r"(?i)(?:continue|save)[^\r\n]*\[(?:y/n|yes/no)\]\s*:?\s*$", clean):
                    if answered:
                        raise ACLError("Cihaz beklenmeyen tekrarlı kaydetme onayı istedi.")
                    self.process.stdin.write("y\n")
                    chunks, answered = [], True
                    continue
                match = pattern.search(clean)
                if not match:
                    continue
                if self.adapter != "hp_1950" and not match[0].strip().endswith("#"):
                    raise ACLError("SSH hesabının yapılandırma yetkisi yok.")
                content = clean[: match.start()].strip()
                if CLI_ERROR.search(content) or re.search(
                    r"(?im)^\s*(?:%\s*)?(?:error\b|failed\b|failure\b|not enough|insufficient|cannot\b|can't\b|ambiguous\b|invalid\b|unrecognized\b)|--\s*more\s*--",
                    content,
                ):
                    raise ACLError(
                        "Cihaz ACL komutunu reddetti. Model, yazılım, lisans ve SSH yetkisini kontrol edin."
                    )
                return content, match[0].strip()

    async def command(self, value, *, save=False):
        self.process.stdin.write(value + "\n")
        output, _ = await self.read(save=save)
        # Command echoes are never part of configuration evidence.
        lines = output.splitlines()
        if lines and (
            lines[0].strip() == value
            or lines[0].rstrip().endswith("# " + value)
            or lines[0].rstrip().endswith(">" + value)
        ):
            lines.pop(0)
        return "\n".join(lines)


@asynccontextmanager
async def connect(device, secret):
    async with asyncssh.connect(
        device.management_ip,
        port=device.config_port,
        username=secret["username"],
        password=secret["password"],
        known_hosts=ssh_known_hosts(device),
        client_keys=[],
        connect_timeout=10,
        login_timeout=15,
        keepalive_interval=10,
        keepalive_count_max=3,
    ) as connection:
        async with connection.create_process(
            term_type="vt100",
            term_size=(240, 40),
            stderr=asyncssh.STDOUT,
            encoding="utf-8",
            errors="replace",
        ) as process:
            shell = Shell(process, device.adapter)
            _, prompt = await shell.read()
            if device.adapter == "hp_1950":
                if secret.get("cli_password"):
                    await enter_extended(process, prompt, secret["cli_password"])
                await shell.command("screen-length disable")
            else:
                await shell.command("no paging" if device.adapter == "aruba_7200" else "no page")
            yield shell
