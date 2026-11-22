"""Node-scoped Mobility Conductor transport for registered 7205 devices.

Managed-device sessions only read. All writes use the central inventory's
Conductor SSH profile, a serialized lease, and a verified device-specific node.
"""

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import ip_address

from sqlalchemy import select

from .. import models as m
from ..core import redis_client, session_factory, settings
from ..identity.security import secret_data
from ..runtime_limits import sql_quick
from ..services import connection_profile
from . import adapters
from .cli import ACLError

MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", re.I)
SYNC_TIMEOUT = 120
POLL_INTERVAL = 2


def access_identity(device):
    return [
        device.management_ip,
        device.adapter,
        device.config_port,
        device.config_credential_id,
        device.ssh_trust_host_key,
    ]


def route_snapshot(db, device):
    host = settings().blacklist_conductor_host
    if device.adapter != "aruba_7200" or not host:
        return None
    try:
        host = str(ip_address(host))
    except ValueError:
        raise ACLError("Conductor adresi geçersiz.") from None
    rows = list(
        db.scalars(
            select(m.Device).where(
                m.Device.management_ip == host,
                m.Device.vrf_id == device.vrf_id,
                m.Device.archived.is_(False),
                m.Device.lifecycle_status == "active",
            )
        )
    )
    if (
        len(rows) != 1
        or rows[0].adapter != "aruba_7200"
        or not re.search(r"ArubaMM|Mobility.?Conductor|Mobility.?Master", rows[0].model, re.I)
    ):
        raise ACLError("Aynı VRF içinde etkin, tekil Mobility Conductor envanter kaydı gerekli.")
    controller = rows[0]
    if db.scalar(
        select(m.FirmwareTarget.id).where(
            m.FirmwareTarget.active_device == controller.id,
            m.FirmwareTarget.status == "running",
        )
    ):
        raise ACLError("Mobility Conductor üzerinde firmware işlemi sürüyor; ACL işlemi durdu.")
    credential = connection_profile(db, controller, "ssh")
    if not credential:
        raise ACLError("Mobility Conductor için kayıtlı SSH erişim profili gerekli.")
    return {
        "device_id": controller.id,
        "endpoint": access_identity(controller),
        "credential_id": credential.id,
        "credential_updated_at": credential.updated_at.isoformat(),
    }


@dataclass
class Route:
    device: object
    secret: dict
    snapshot: dict


def load_route(db, device, snapshot):
    if route_snapshot(db, device) != snapshot:
        raise ACLError("Conductor hedefi veya erişimi değişti; yeniden eşitleyin.")
    if snapshot is None:
        return None
    controller = db.get(m.Device, snapshot["device_id"])
    secret = secret_data(connection_profile(db, controller, "ssh"))
    db.expunge(controller)
    return Route(controller, secret, snapshot)


def check_route(device_id, snapshot):
    with session_factory()() as db:
        device = db.get(m.Device, device_id)
        if not device or route_snapshot(db, device) != snapshot:
            raise ACLError("Conductor hedefi veya erişimi işlem sırasında değişti.")


def table_rows(output, required):
    """Read fixed-width CLI tables; do not guess columns from row whitespace."""
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not index or not re.fullmatch(r"\s*-{2,}(?:\s+-{2,})*\s*", line):
            continue
        spans = list(re.finditer(r"-{2,}", line))
        starts = [match.start() for match in spans]
        ends = starts[1:] + [None]
        names = [lines[index - 1][a:b].strip() for a, b in zip(starts, ends)]
        if not set(required) <= set(names):
            continue
        result = []
        for row in lines[index + 1 :]:
            if not row.strip():
                continue
            if row.strip().startswith("Total "):
                break
            result.append({name: row[a:b].strip() for name, a, b in zip(names, starts, ends)})
        return result
    raise ACLError("Conductor tablo biçimi doğrulanamadı; cihaz eşlemesi yapılmadı.")


def safe_path(path):
    return bool(re.fullmatch(r"/md(?:/[A-Za-z0-9_.:-]+)+", path)) and not any(
        part in (".", "..") for part in path.split("/")
    )


@dataclass(frozen=True)
class Node:
    path: str
    mac: str


def resolve_node(switches, devices, hierarchy, address):
    matches = [
        row
        for row in table_rows(switches, ["IP Address", "MAC", "Nodepath", "Model", "Type", "Status"])
        if row["IP Address"] == address
    ]
    if len(matches) != 1:
        raise ACLError("Conductor üzerinde hedef IP tekil olarak eşlenemedi.")
    row = matches[0]
    mac = row["MAC"].lower()
    if (
        not MAC.fullmatch(mac)
        or row["Type"].upper() != "MD"
        or row["Status"].lower() != "up"
        or not re.fullmatch(r"(?:Aruba|A)?7205", row["Model"], re.I)
    ):
        raise ACLError("Conductor hedefi etkin bir 7205 olarak doğrulanamadı.")
    provisioned = [
        r for r in table_rows(devices, ["Device", "Model", "Nodepath"]) if r["Device"].lower() == mac
    ]
    nodes = [
        r["Config Node"]
        for r in table_rows(hierarchy, ["Config Node", "Type"])
        if r["Type"].lower() == "device" and r["Config Node"].rsplit("/", 1)[-1].lower() == mac
    ]
    if len(provisioned) != 1 or len(nodes) != 1 or not safe_path(nodes[0]):
        raise ACLError("7205 için güvenilir, tekil cihaz düğümü bulunamadı.")
    path = nodes[0]
    if any(
        value not in (path, path.rsplit("/", 1)[0]) for value in (row["Nodepath"], provisioned[0]["Nodepath"])
    ):
        raise ACLError("Conductor IP/MAC/düğüm eşlemeleri birbiriyle çelişiyor.")
    return Node(path, mac)


def unsaved_nodes(output):
    rows = table_rows(output, ["Nodename"])
    paths = {row["Nodename"].rstrip("/") or "/" for row in rows}
    if any(not path.startswith("/") or re.search(r"\s", path) for path in paths):
        raise ACLError("Conductor bekleyen düğüm listesi çözümlenemedi.")
    return paths


def related(left, right):
    return (
        left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")
    )


def switch_state(output, address):
    rows = [
        row
        for row in table_rows(output, ["IP Address", "Status", "Configuration State", "Config ID"])
        if row["IP Address"] == address
    ]
    if len(rows) != 1 or not rows[0]["Config ID"].isdigit():
        raise ACLError("Hedef 7205 dağıtım durumu tekil olarak doğrulanamadı.")
    row = rows[0]
    return row["Status"].lower() == "up" and row["Configuration State"] == "UPDATE SUCCESSFUL", int(
        row["Config ID"]
    )


@asynccontextmanager
async def lease(route):
    lock = redis_client().lock(
        "netrix:blacklist:conductor:" + route.device.id, timeout=660, thread_local=False
    )
    acquired = await asyncio.to_thread(lock.acquire, blocking=True, blocking_timeout=120)
    if not acquired:
        raise ACLError("Conductor başka bir NETRIX işi tarafından kullanılıyor; yeniden eşitleyin.")
    try:
        yield lock
    finally:
        if await asyncio.to_thread(lock.owned):
            await asyncio.to_thread(lock.release)


class Session:
    def __init__(self, writer, reader, route, device, target, lock, check, progress):
        self.writer, self.reader, self.route, self.device = writer, reader, route, device
        self.target, self.lock, self.check, self.progress = target, lock, check, progress
        self.node = None
        self.original_unsaved = set()
        self.allowed = {}
        self.context = None
        self.profiles = [p for p in [target["profile"], *target["stale_profiles"]] if p]

    async def guard(self):
        await self.check()
        await sql_quick(check_route, self.device.id, self.route.snapshot)
        if not await asyncio.to_thread(self.lock.owned):
            raise ACLError("Conductor yazma kilidi kaybedildi; sonraki komutlar durduruldu.")

    async def mapping(self):
        return resolve_node(
            await self.writer.command("show switches debug"),
            await self.writer.command("show configuration devices"),
            await self.writer.command("show configuration node-hierarchy"),
            self.device.management_ip,
        )

    async def scope(self):
        if (await self.writer.command("pwd")).strip() != self.node.path:
            raise ACLError("Conductor oturumu hedef cihaz düğümünde değil; işlem durdu.")

    async def prepare(self):
        await self.guard()
        cfg = await self.reader.command("show running-config")
        references = re.findall(r"(?m)^\s*(?:conductorip|masterip)\s+(\d+\.\d+\.\d+\.\d+)\b", cfg)
        if set(references) != {self.route.device.management_ip}:
            raise ACLError("7205'in Conductor adresi kayıtlı yönlendirmeyle eşleşmiyor.")
        self.node = await self.mapping()
        self.original_unsaved = unsaved_nodes(await self.writer.command("show configuration unsaved-nodes"))
        if any(related(path, self.node.path) for path in self.original_unsaved):
            raise ACLError(
                "Conductor cihaz düğümünde veya üst/alt düğümde bekleyen değişiklik var; otomatik commit yapılmadı."
            )
        await self.writer.command("cd " + self.node.path)
        await self.scope()
        if (await self.writer.command("show configuration pending")).strip():
            raise ACLError("Conductor düğümünde önceden bekleyen değişiklik var; işlem durdu.")
        await self.ownership()
        await self.progress(
            "preflight", conductor_ip=self.route.device.management_ip, node_path=self.node.path
        )

    async def effective(self):
        await self.scope()
        cfg = await self.writer.command("show configuration effective")
        refs = re.findall(r"(?m)^\s*(?:conductorip|masterip)\s+(\d+\.\d+\.\d+\.\d+)\b", cfg)
        if set(refs) != {self.route.device.management_ip} or not re.search(r"(?m)^controller-ip\s+\S+", cfg):
            raise ACLError("Conductor etkin cihaz yapılandırması eksik veya yanlış düğüme ait.")
        return cfg

    async def ownership(self):
        """Never remove or override an ACL inherited from a shared parent."""
        effective = await self.effective()
        local = await self.writer.command("show configuration committed")
        parsed, local_blocks = adapters.blocks(effective), adapters.blocks(local)
        local_by_header = dict(local_blocks)
        detail = await self.writer.command("show configuration effective detail")
        wanted = set()
        bindings = set()
        for profile in self.profiles:
            header, bind = adapters.acl_identity("aruba_7200", profile)
            wanted.update((header, "netdestination " + adapters.alias_for(header)))
            bindings.add(bind)
        for header in wanted:
            body = adapters.matching_acl(parsed, header, "aruba_7200")
            local_body = adapters.matching_acl(local_blocks, header, "aruba_7200")
            if body is not None and (local_body is None or body != local_body):
                raise ACLError(
                    "Hedef NETRIX ACL/nesnesi üst düğümden miras alınıyor; ortak politika değiştirilmedi."
                )
        for header, body in parsed:
            if header.startswith("interface "):
                for bind in set(body) & bindings:
                    if bind not in local_by_header.get(header, []):
                        raise ACLError("ACL port bağlantısı üst düğümden miras alınıyor; silme/yazma durdu.")
        seen = set()
        for line in detail.splitlines():
            content, separator, origin = line.partition("#")
            normalized = " ".join(adapters.words(content))
            if normalized in wanted or normalized in bindings:
                seen.add(normalized)
                if not separator or not re.fullmatch(
                    r"\s*local \[" + re.escape(self.node.path) + r"\]\s*", origin
                ):
                    raise ACLError("ACL veya port bağlantısının yerel düğüm sahipliği doğrulanamadı.")
        present = {header for header, _ in parsed if header in wanted}
        if not present <= seen:
            raise ACLError("ACL düğüm kaynağı detay çıktısında doğrulanamadı.")
        self.baseline_blocks = local_by_header
        return effective

    async def command(self, command, *, save=False):
        if command == "show running-config":
            return await self.effective()
        if command == "show interface":
            return await self.reader.command(command)
        await self.guard()
        if command == "configure terminal":
            await self.scope()
            self.context = None
        elif command in ("exit", "end"):
            self.context = None
        else:
            normalized = " ".join(adapters.words(command)).removesuffix(" position 1")
            if command.startswith(("ip access-list session ", "netdestination ", "interface ")):
                self.context = normalized
                self.allowed.setdefault(normalized, set())
            else:
                self.allowed.setdefault(self.context, set()).add(normalized)
        return await self.writer.command(command, save=save)

    def validate_pending(self, output):
        for header, body in adapters.blocks(output):
            if header not in self.allowed:
                if header not in self.allowed.get(None, set()):
                    raise ACLError(
                        "Conductor pending farkında NETRIX planı dışında komut var; commit yapılmadı."
                    )
            for line in body:
                if line not in self.allowed.get(header, set()) and line not in self.baseline_blocks.get(
                    header, []
                ):
                    raise ACLError("Conductor pending farkında beklenmeyen kural var; commit yapılmadı.")

    async def finish(self, plans):
        await self.guard()
        await self.scope()
        if await self.mapping() != self.node:
            raise ACLError("Conductor cihaz eşlemesi işlem sırasında değişti; commit yapılmadı.")
        paths = unsaved_nodes(await self.writer.command("show configuration unsaved-nodes"))
        if paths - self.original_unsaved - {self.node.path}:
            raise ACLError("Conductor üzerinde başka bekleyen değişiklik oluştu; commit yapılmadı.")
        pending = await self.writer.command("show configuration pending")
        self.validate_pending(pending)
        _, baseline_id = switch_state(await self.writer.command("show switches"), self.device.management_ip)
        changed = bool(pending.strip())
        if changed:
            await self.progress("saving", node_path=self.node.path)
            await self.guard()
            await self.scope()
            paths = unsaved_nodes(await self.writer.command("show configuration unsaved-nodes"))
            if paths - self.original_unsaved - {self.node.path}:
                raise ACLError("Conductor üzerinde başka bekleyen değişiklik oluştu; commit yapılmadı.")
            if await self.writer.command("show configuration pending") != pending:
                raise ACLError("Conductor pending farkı kayıt öncesinde değişti; commit yapılmadı.")
            await self.writer.command("write memory", save=True)
        await self.progress("verifying", node_path=self.node.path)
        stop_at = asyncio.get_running_loop().time() + SYNC_TIMEOUT
        while True:
            await self.guard()
            ready, config_id = switch_state(
                await self.writer.command("show switches"), self.device.management_ip
            )
            if ready and (not changed or config_id > baseline_id):
                await self.scope()
                if not (await self.writer.command("show configuration pending")).strip():
                    effective = await self.ownership()
                    current = await self.reader.command("show running-config")
                    ports = await self.reader.command("show interface")
                    try:
                        for plan in plans:
                            adapters.verify(plan, effective, ports)
                            adapters.verify(plan, current, ports)
                    except ACLError:
                        pass  # The managed device can lag behind the Conductor status.
                    else:
                        await self.progress("verified", node_path=self.node.path, config_id=config_id)
                        return
            if asyncio.get_running_loop().time() >= stop_at:
                raise ACLError(
                    "Conductor dağıtımı/7205 geri okuması zamanında doğrulanamadı; başarı sayılmadı."
                )
            await asyncio.sleep(POLL_INTERVAL)
