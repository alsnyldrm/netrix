"""NETRIX protocol boundary. No calls occur during imports or tests."""

import asyncio
import ipaddress
import json
from typing import Protocol

import asyncssh
import httpx
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    Udp6TransportTarget,
    UdpTransportTarget,
    UsmUserData,
    bulk_walk_cmd,
    get_cmd,
    usmAesCfb128Protocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMACSHAAuthProtocol,
    walk_cmd,
)
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

from ..configuration.fortios import fetch_fortios_backup
from ..configuration.validation import SSH_BACKUP_ADAPTERS, BackupError, validate_cli_output
from ..core import settings
from .aruba import ARUBA_ADAPTERS, read_aruba, read_neighbor_detail
from .comware import read_comware
from .identification import rest_identity, snmp_identity, ssh_identity
from .neighbor_detail import AOS_SWITCH
from .neighbors import parse_neighbors


class NetworkError(Exception):
    pass


class Collector(Protocol):
    async def collect(self, host: str, port: int, secret: dict) -> dict: ...


SYSTEM = {
    "sys_description": "1.3.6.1.2.1.1.1.0",
    "sys_object_id": "1.3.6.1.2.1.1.2.0",
    "uptime": "1.3.6.1.2.1.1.3.0",
    "hostname": "1.3.6.1.2.1.1.5.0",
}
TABLES = {
    "entity_class": "1.3.6.1.2.1.47.1.1.1.1.5",
    "entity_vendor": "1.3.6.1.2.1.47.1.1.1.1.12",
    "entity_model": "1.3.6.1.2.1.47.1.1.1.1.13",
    "entity_software": "1.3.6.1.2.1.47.1.1.1.1.10",
    "if_name": "1.3.6.1.2.1.31.1.1.1.1",
    "if_descr": "1.3.6.1.2.1.2.2.1.2",
    "if_alias": "1.3.6.1.2.1.31.1.1.1.18",
    "if_mac": "1.3.6.1.2.1.2.2.1.6",
    "if_speed": "1.3.6.1.2.1.31.1.1.1.15",
    "if_status": "1.3.6.1.2.1.2.2.1.8",
    "lldp_local_type": "1.0.8802.1.1.2.1.3.7.1.2",
    "lldp_local_desc": "1.0.8802.1.1.2.1.3.7.1.4",
    "lldp_chassis_type": "1.0.8802.1.1.2.1.4.1.1.4",
    "lldp_chassis": "1.0.8802.1.1.2.1.4.1.1.5",
    "lldp_port_type": "1.0.8802.1.1.2.1.4.1.1.6",
    "lldp_port_desc": "1.0.8802.1.1.2.1.4.1.1.8",
    "lldp_local_id": "1.0.8802.1.1.2.1.3.7.1.3",
    "lldp_name": "1.0.8802.1.1.2.1.4.1.1.9",
    "lldp_port": "1.0.8802.1.1.2.1.4.1.1.7",
    "cdp_name": "1.3.6.1.4.1.9.9.23.1.2.1.1.6",
    "cdp_sysname": "1.3.6.1.4.1.9.9.23.1.2.1.1.17",
    "cdp_port": "1.3.6.1.4.1.9.9.23.1.2.1.1.7",
    "arp_mac": "1.3.6.1.2.1.4.22.1.2",
    "ndp_mac": "1.3.6.1.2.1.4.35.1.4",
    "fdb_port": "1.3.6.1.2.1.17.4.3.1.2",
    "bridge_ifindex": "1.3.6.1.2.1.17.1.4.1.2",
    "vlan_fdb_port": "1.3.6.1.2.1.17.7.1.2.2.1.2",
}

# IPAM reads address/bridge evidence only. No traffic counters are collected.
IPAM_TABLES = {
    **{key: oid for key, oid in TABLES.items() if not key.startswith("entity_")},
    "arp_type": "1.3.6.1.2.1.4.22.1.4",
    "ndp_type": "1.3.6.1.2.1.4.35.1.6",
    "ndp_state": "1.3.6.1.2.1.4.35.1.7",
    "ip_addr_ifindex": "1.3.6.1.2.1.4.20.1.2",
    "ip_addr_address": "1.3.6.1.2.1.4.20.1.1",
    "ip_addr_mask": "1.3.6.1.2.1.4.20.1.3",
    "ip_address_ifindex": "1.3.6.1.2.1.4.34.1.3",
    "ip_address_prefix": "1.3.6.1.2.1.4.34.1.5",
    "vlan_fdb_id": "1.3.6.1.2.1.17.7.1.4.2.1.3",
    "vlan_fdb_status": "1.3.6.1.2.1.17.7.1.2.2.1.3",
}


def ipv4_value(value):
    """Agents may encode IP-MIB addresses/masks as raw four-octet strings."""
    try:
        octets = value.asOctets() if hasattr(value, "asOctets") else value
        if isinstance(octets, bytes) and len(octets) == 4:
            return str(ipaddress.IPv4Address(octets))
        return str(ipaddress.IPv4Address(str(value)))
    except (ValueError, TypeError):
        return ""


def number(value, default=None):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def mac(value):
    if hasattr(value, "asOctets"):
        raw = value.asOctets()
        if len(raw) == 6:
            return ":".join(f"{b:02x}" for b in raw)
    return ""


class SNMPCollector:
    async def ipam(self, host, port, secret):
        return await self._collect(host, port, secret, ipam_only=True)

    async def collect(self, host, port, secret):
        return await self._collect(host, port, secret)

    async def identify(self, host, port, secret):
        return await self._collect(host, port, secret, identity_only=True)

    async def probe(self, host, port, secret):
        return await self._collect(host, port, secret, probe_only=True)

    async def discovery_probe(self, host, port, secret):
        return await self._collect(host, port, secret, probe_only=True, fast_probe=True)

    async def _collect(
        self, host, port, secret, identity_only=False, probe_only=False, fast_probe=False, ipam_only=False
    ):
        snmp = SnmpEngine()
        try:
            if secret.get("protocol", "snmpv3") == "snmpv2c":
                auth = CommunityData(secret["community"], mpModel=1)
            else:
                auth = UsmUserData(
                    secret["username"],
                    secret["auth_key"],
                    secret["priv_key"],
                    authProtocol=usmHMAC192SHA256AuthProtocol
                    if secret.get("auth_protocol", "sha256") == "sha256"
                    else usmHMACSHAAuthProtocol,
                    privProtocol=usmAesCfb128Protocol,
                )
            transport_type = (
                Udp6TransportTarget if ipaddress.ip_address(host).version == 6 else UdpTransportTarget
            )
            target = await transport_type.create((host, port), timeout=1 if fast_probe else 2, retries=1)
            context = ContextData()
            tables, unsupported = {}, []
            async with asyncio.timeout(180):
                system_oids = {**SYSTEM, **({"ip_forwarding": "1.3.6.1.2.1.4.1.0"} if ipam_only else {})}
                error, status, _, values = await get_cmd(
                    snmp,
                    auth,
                    target,
                    context,
                    *[ObjectType(ObjectIdentity(oid)) for oid in system_oids.values()],
                    lookupMib=False,
                )
                if error or status:
                    raise NetworkError("SNMP erişimi başarısız")
                system = {key: str(values[i][1]) for i, key in enumerate(system_oids)}
                system["uptime"] = number(values[2][1], 0)
                if probe_only:
                    if number(values[2][1]) is None:
                        raise NetworkError("SNMP sistem OID okuması başarısız")
                    return
                limit = 16384 if ipam_only else 2048
                for key, oid in (IPAM_TABLES if ipam_only else TABLES).items():
                    if identity_only and not key.startswith("entity_"):
                        continue
                    table = {}
                    walker = bulk_walk_cmd if ipam_only else walk_cmd
                    async for error, status, _, bindings in walker(
                        snmp,
                        auth,
                        target,
                        context,
                        *([0, 25] if ipam_only else []),
                        ObjectType(ObjectIdentity(oid)),
                        lexicographicMode=False,
                        lookupMib=False,
                        maxRows=limit,
                        maxCalls=limit,
                    ):
                        if error or status:
                            unsupported.append(key)
                            break
                        for binding in bindings:
                            if isinstance(binding[1], (EndOfMibView, NoSuchInstance, NoSuchObject)):
                                unsupported.append(key)
                                continue
                            if not str(binding[0]).startswith(oid + "."):
                                unsupported.append(key)
                                continue
                            index = str(binding[0])[len(oid) + 1 :]
                            table[index] = binding[1]
                    tables[key] = table
                for key, table in tables.items():
                    if len(table) >= limit:
                        unsupported.append(key)
                system["identity"] = snmp_identity(system, tables)
                if identity_only:
                    return system
                interfaces = []
                for index, label in tables["if_descr"].items():
                    if not index.isdigit():
                        continue
                    item = {
                        "if_index": int(index),
                        "name": str(tables["if_name"].get(index, label))[:120],
                        "description": str(label)[:400],
                        "mac_address": mac(tables["if_mac"].get(index)),
                        "speed_bps": (number(tables["if_speed"].get(index)) or 0) * 1000000 or None,
                        "oper_status": "up"
                        if number(tables["if_status"].get(index)) == 1
                        else "unknown"
                        if index not in tables["if_status"]
                        else "down",
                    }
                    interfaces.append(item)
                neighbors = parse_neighbors(tables)
                raw = {
                    key: {
                        i: mac(v)
                        if key in ("arp_mac", "ndp_mac")
                        else ipv4_value(v)
                        if key in ("ip_addr_mask", "ip_addr_address")
                        else str(v)
                        for i, v in tables[key].items()
                    }
                    for key in (
                        tuple(IPAM_TABLES)
                        if ipam_only
                        else ("arp_mac", "ndp_mac", "fdb_port", "bridge_ifindex", "vlan_fdb_port")
                    )
                }
                return {
                    **system,
                    "interfaces": interfaces,
                    "neighbors": neighbors,
                    "neighbor_protocols_complete": [
                        protocol
                        for protocol, required in {
                            "lldp": (
                                "lldp_name",
                                "lldp_chassis",
                                "lldp_port",
                                "lldp_local_id",
                                "lldp_local_desc",
                                "lldp_local_type",
                                "lldp_chassis_type",
                                "lldp_port_type",
                                "lldp_port_desc",
                                "if_name",
                                "if_descr",
                            ),
                            "cdp": ("cdp_name", "cdp_port", "if_name", "if_descr"),
                        }.items()
                        if not any(key in unsupported for key in required)
                        and any(tables[key] for key in required if key.startswith(protocol))
                    ],
                    "tables": raw,
                    "unsupported": unsupported,
                }
        except TimeoutError as exc:
            raise NetworkError("SNMP toplama zaman aşımı") from exc
        finally:
            snmp.close_dispatcher()


COMMANDS = {
    "ios": "show running-config",
    "junos": "show configuration | display set | no-more",
    "linux": "ip -details address show; ip route show table all; ip -6 route show table all",
}

IDENTITY_COMMANDS = {
    "ios": "show version",
    "junos": "show version | no-more",
    "fortios": "get system status",
    "linux": (
        "printf '\\nNETRIX_VENDOR='; cat /sys/class/dmi/id/sys_vendor 2>/dev/null; "
        "printf '\\nNETRIX_MODEL='; cat /sys/class/dmi/id/product_name 2>/dev/null; "
        "printf '\\nNETRIX_CHASSIS='; cat /sys/class/dmi/id/chassis_type 2>/dev/null; printf '\\n'"
    ),
}


def ssh_known_hosts(device):
    """Use the explicitly saved device policy for every SSH operation."""
    return None if getattr(device, "ssh_trust_host_key", False) is True else settings().known_hosts


async def fetch_neighbor_detail(device, secret, ports=()):
    if device.adapter not in AOS_SWITCH:
        return {}
    async with asyncio.timeout(60):
        async with asyncssh.connect(
            device.management_ip,
            port=device.config_port,
            username=secret["username"],
            password=secret["password"],
            known_hosts=ssh_known_hosts(device),
            client_keys=[],
            connect_timeout=10,
            login_timeout=15,
        ) as connection:
            return await read_neighbor_detail(connection, ports)


async def fetch_identity(device, secret):
    """Read only identity output. Never retain raw CLI/API responses containing secrets."""
    async with asyncio.timeout(60):
        if device.adapter == "rest":
            host = f"[{device.management_ip}]" if ":" in device.management_ip else device.management_ip
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
                async with client.stream(
                    "GET",
                    f"https://{host}:{device.config_port}{device.identity_path}",
                    headers={"Authorization": f"Bearer {secret['token']}"},
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 256 * 1024:
                            raise NetworkError("Cihaz kimlik yanıtı boyut sınırını aşıyor")
                    return rest_identity(json.loads(body))
        if (
            device.adapter not in IDENTITY_COMMANDS
            and device.adapter not in ARUBA_ADAPTERS
            and device.adapter != "hp_1950"
        ):
            raise NetworkError("Kimlik sorgusu adaptörü desteklenmiyor")
        async with asyncssh.connect(
            device.management_ip,
            port=device.config_port,
            username=secret["username"],
            password=secret["password"],
            known_hosts=ssh_known_hosts(device),
            client_keys=[],
            connect_timeout=10,
            login_timeout=15,
        ) as connection:
            if device.adapter in ARUBA_ADAPTERS:
                return ssh_identity(device.adapter, await read_aruba(connection, device.adapter))
            if device.adapter == "hp_1950":
                return ssh_identity(
                    device.adapter,
                    await read_comware(connection, cli_password=secret.get("cli_password", "")),
                )
            result = await connection.run(IDENTITY_COMMANDS[device.adapter], check=True, timeout=30)
            if len(result.stdout.encode()) > 256 * 1024:
                raise NetworkError("Cihaz kimlik yanıtı boyut sınırını aşıyor")
            return ssh_identity(device.adapter, result.stdout)


async def fetch_config(device, secret):
    if device.adapter not in SSH_BACKUP_ADAPTERS:
        raise BackupError("ssh_required")
    async with asyncio.timeout(90):
        async with asyncssh.connect(
            device.management_ip,
            port=device.config_port,
            username=secret["username"],
            password=secret["password"],
            known_hosts=ssh_known_hosts(device),
            client_keys=[],
            connect_timeout=10,
            login_timeout=15,
        ) as connection:
            if device.adapter == "fortios":
                return await fetch_fortios_backup(connection)
            if device.adapter in ARUBA_ADAPTERS:
                return await read_aruba(connection, device.adapter, backup=True)
            if device.adapter == "hp_1950":
                return await read_comware(
                    connection, backup=True, cli_password=secret.get("cli_password", "")
                )
            # A fresh read-only session; no device configuration commands.
            result = await connection.run(COMMANDS[device.adapter], check=True, timeout=60)
            validate_cli_output(result.stdout)
            return result.stdout
