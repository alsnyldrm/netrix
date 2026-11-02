"""Capability-specific firmware CLI; never accepts arbitrary user commands."""

import asyncio
import re
from contextlib import asynccontextmanager

import asyncssh

from ..core import settings
from ..discovery.aruba import CLI_ERROR, PROMPT, terminal_text
from ..discovery.comware import PROMPT as HP_PROMPT
from ..discovery.protocols import ssh_known_hosts
from ..discovery.software_version import software_version

ERRORS = {
    "cli": "Cihaz komutu reddetti. Model, sürüm ve yönetici yetkisini kontrol edin.",
    "prompt": "Cihazın komut istemi doğrulanamadı.",
    "version": "Çalışan yazılım sürümü kesin olarak okunamadı.",
    "bank": "Çalışan imaj alanı okunamadı; üzerine yazma engellendi.",
    "image": "İmajın hedef bankaya yazıldığı doğrulanamadı.",
    "source_key": "Dosya sunucusunun SSH anahtarı doğrulanamadı.",
    "unexpected_prompt": "Cihaz beklenmeyen bir onay istedi; işlem durduruldu.",
    "space": "Cihaz yeterli boş alan bildirmiyor.",
    "sftp_service": "Cihazda SFTP başlatılamadı. SFTP erişimini kontrol edin veya planda SFTP hazırlığını açıkça onaylayın; bu ayar TFTP'yi kapatır.",
    "topology": "Stack/VSF üyeleri sağlıklı değil; firmware işlemi durduruldu.",
}


class FirmwareError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(ERRORS.get(code, "Firmware işlemi doğrulanamadı."))


def version_key(value):
    value = re.sub(r"RELEASE\s*", "R", value.upper())
    return re.sub(r"[^A-Z0-9]", "", value)


def matches_version(expected, actual):
    expected, actual = version_key(expected), version_key(actual)
    return bool(
        expected
        and actual
        and (expected == actual or (expected.startswith("R") and actual.endswith(expected)))
    )


def current_version(text, adapter):
    value = software_version(text, adapter)
    if not value and adapter == "hp_1950":
        match = re.search(r"(?im)^\s*(?:Current\s+)?(?:Software|Comware)\s+version\s*:\s*(.+)$", text)
        value = match[1].strip() if match else ""
    if not value:
        raise FirmwareError("version")
    return value


def active_bank(text):
    found = {
        m[1].lower()
        for m in re.finditer(r"(?im)^\s*(?:Boot Image|Active Image)\s*:\s*(primary|secondary)\s*$", text)
    }
    if len(found) != 1:
        raise FirmwareError("bank")
    return found.pop()


def bank_contains(text, bank, expected):
    # A line must identify the requested bank and the exact complete revision.
    for line in text.splitlines():
        if re.search(r"\b" + bank + r"\b", line, re.I):
            tokens = re.findall(r"[A-Z]{1,4}\.\d+(?:\.\d+){2,}|R\d+P\d+", line, re.I)
            if any(matches_version(expected, token) for token in tokens):
                return True
    # CX show images has Primary Image / Secondary Image section headings.
    section = re.search(
        r"(?is)\b" + bank + r"\s+Image\s*[:\n](.*?)(?=\b(?:Primary|Secondary)\s+Image|\Z)", text
    )
    if section:
        return any(
            matches_version(expected, token)
            for token in re.findall(r"[A-Z]{1,4}\.\d+(?:\.\d+){2,}", section[1], re.I)
        )
    return False


class CLI:
    def __init__(self, process, adapter, *, key_fingerprints=()):
        self.process, self.adapter = process, adapter
        self.prompt = None
        self.fingerprints = key_fingerprints

    async def read(self, *, action="read", password=None, timeout=60, disconnect=False):
        output, used, supplied = "", 0, False
        pattern = (
            re.compile(r"(?m)^" + re.escape(self.prompt) + r"[ \t\r\n]*\Z")
            if self.prompt
            else (HP_PROMPT if self.adapter == "hp_1950" else PROMPT)
        )
        async with asyncio.timeout(timeout):
            while True:
                chunk = await self.process.stdout.read(8192)
                if not chunk:
                    if disconnect:
                        return terminal_text(output)
                    raise FirmwareError("prompt")
                output += chunk
                if len(output) > 8 * 1024 * 1024:
                    raise FirmwareError("prompt")
                clean = terminal_text(output)
                tail = clean[used:]
                if not self.prompt and re.search(r"press any key to continue", tail, re.I):
                    self.process.stdin.write(" ")
                    used = len(clean)
                    continue
                if re.search(r"(?i)password\s*:\s*$", tail):
                    if action != "transfer" or not password or supplied:
                        raise FirmwareError("unexpected_prompt")
                    self.process.stdin.write(password + "\n")
                    supplied, used = True, len(clean)
                    continue
                if (
                    re.search(r"(?i)(?:yes/no|yes/no/\[fingerprint\]).*\??\s*$", tail)
                    and "authenticity" in tail.lower()
                ):
                    if action != "transfer" or not any(f in tail for f in self.fingerprints):
                        raise FirmwareError("source_key")
                    self.process.stdin.write("yes\n")
                    used = len(clean)
                    continue
                if re.search(r"(?i)(?:\[(?:y/n|yes/no)\]|\((?:y/n|yes/no)\)|continue\s*\?).*[:?]?\s*$", tail):
                    if action not in ("transfer", "boot", "save") or not re.search(
                        r"(?i)(?:continue|reboot|restart|save|overwrite|delete.*\.ipe|main.*startup|current configuration|boot.*image)",
                        tail,
                    ):
                        raise FirmwareError("unexpected_prompt")
                    self.process.stdin.write("n\n" if re.search(r"(?i)delete.*\.ipe", tail) else "y\n")
                    used = len(clean)
                    continue
                if action in ("boot", "save") and re.search(
                    r"(?i)(?:input|enter).*file\s*name.*\.cfg[^\r\n]*[:?]\s*$", tail
                ):
                    self.process.stdin.write("\n")
                    used = len(clean)
                    continue
                match = pattern.search(clean)
                if match:
                    self.prompt = match[0].strip()
                    if self.adapter != "hp_1950" and not self.prompt.endswith("#"):
                        raise FirmwareError("prompt")
                    content = clean[: match.start()]
                    if CLI_ERROR.search(content) or re.search(
                        r"(?im)^\s*(?:Error:|Failed to|Not enough space|Insufficient space)", content
                    ):
                        raise FirmwareError("cli")
                    return content

    async def command(self, command, **kwargs):
        self.process.stdin.write(command + "\n")
        return await self.read(**kwargs)


@asynccontextmanager
async def connect(device, secret, *, key_fingerprints=()):
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
            term_type="vt100", term_size=(200, 40), stderr=asyncssh.STDOUT
        ) as process:
            cli = CLI(process, device.adapter, key_fingerprints=key_fingerprints)
            await cli.read()
            if device.adapter != "hp_1950":
                await cli.command("no page")
            yield connection, cli


async def inspect(cli, device):
    if device.adapter == "hp_1950":
        output = await cli.command("summary")
        version = current_version(output, device.adapter)
        bank, banks = "main", output
    else:
        output = await cli.command("show version")
        version = current_version(output, device.adapter)
        bank = active_bank(output)
        banks = await cli.command("show images" if device.adapter == "aruba_6100" else "show flash")
    # Fail on explicit degraded member/management status; never infer ISSU support.
    if re.search(r"(?im)^.*\b(?:member|module)\b.*\b(?:missing|failed|faulted)\b", output + banks):
        raise FirmwareError("topology")
    return {"version": version, "bank": bank, "banks": banks}


async def stage(connection, cli, device, image, bank, path, source, progress=None):
    if device.adapter in ("aruba_5400", "aruba_2900"):
        before_log = set((await cli.command("show logging -r")).splitlines())
        async with connection.start_sftp_client() as sftp:
            # Existing file only: AOS-S does not permit creating /os filenames.
            async with sftp.open("/os/" + bank, "wb") as remote:
                with path.open("rb") as local:
                    size = 0
                    while chunk := await asyncio.to_thread(local.read, 256 * 1024):
                        await remote.write(chunk)
                        size += len(chunk)
                        if progress:
                            progress(size)
        # SFTP returns before flash programming completes on AOS-S.
        async with asyncio.timeout(300):
            while True:
                banks = await cli.command("show flash")
                log = await cli.command("show logging -r")
                updated = any(
                    line not in before_log and re.search(rf"(?i)update:.*\b{bank}\s+Image updated", line)
                    for line in log.splitlines()
                )
                if updated and bank_contains(banks, bank, image.version):
                    return
                await asyncio.sleep(3)
    elif device.adapter == "aruba_6100":
        command = f"copy sftp://{source['username']}@{settings().firmware_advertise_host}:{settings().firmware_sftp_port}/{source['filename']} {bank} vrf default"
        await cli.command(command, action="transfer", password=source["password"], timeout=1800)
        if not bank_contains(await cli.command("show images"), bank, image.version):
            raise FirmwareError("image")
    else:
        await cli.command(
            f"upgrade {settings().firmware_advertise_host} runtime file {source['filename']}",
            action="transfer",
            timeout=1800,
        )
        summary = await cli.command("summary")
        # HP startup .bin names carry release tokens, not necessarily full Comware version.
        expected = re.search(r"(?:R|Release\s*)(\d+(?:P\d+)?)", image.version, re.I)
        if not expected or not re.search(r"(?is)main.*" + re.escape(expected[1]), summary):
            raise FirmwareError("image")


async def activate(cli, device, bank):
    command = (
        "reboot"
        if device.adapter == "hp_1950"
        else f"boot system {bank}"
        if device.adapter == "aruba_6100"
        else f"boot system flash {bank}"
    )
    try:
        await cli.command(command, action="boot", timeout=120, disconnect=True)
    except (asyncssh.ConnectionLost, asyncssh.DisconnectError, BrokenPipeError):
        # A reboot can close SSH before a final prompt; success requires later readback.
        pass


async def probe_sftp(connection):
    try:
        async with connection.start_sftp_client() as sftp:
            await sftp.stat("/os/primary")
    except (asyncssh.Error, OSError):
        raise FirmwareError("sftp_service") from None


async def enable_sftp(cli):
    # Only a plan carrying explicit permission may change this device setting.
    cli.process.stdin.write("configure terminal\n")
    cli.prompt = None
    await cli.read()
    await cli.command("ip ssh filetransfer", action="save")
    cli.process.stdin.write("exit\n")
    cli.prompt = None
    await cli.read()
