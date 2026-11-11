"""AOS-CX MAC/VLAN evidence for inventory, independent of Q-BRIDGE FID numbering."""

import asyncio
import re
from collections import defaultdict

import asyncssh

from ..configuration.validation import BackupError
from .aruba import CLI_ERROR, read_prompt

HEADER = re.compile(r"^MAC Address\s+VLAN\s+Type\s+Port\s*$", re.I | re.M)
COUNT = re.compile(r"^Number of MAC addresses\s*:\s*(\d+)\s*$", re.I | re.M)
ROW = re.compile(r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s+(\d+)\s+([\w-]+)\s+(\S+)", re.I)
PHYSICAL = re.compile(r"\d+/\d+/\d+")


def parse_mac_vlans(output):
    header, count = HEADER.search(output), COUNT.search(output)
    if CLI_ERROR.search(output) or not header or not count:
        raise BackupError("aruba_mac_table_incomplete")
    rows = [line.strip() for line in output[header.end() :].splitlines() if line.strip().strip("-")]
    if len(rows) != int(count[1]):
        raise BackupError("aruba_mac_table_incomplete")
    candidates = defaultdict(set)
    for line in rows:
        row = ROW.fullmatch(line)
        if not row:
            raise BackupError("aruba_mac_table_incomplete")
        mac, vlan, kind, port = row.groups()
        vlan = int(vlan)
        if 1 <= vlan <= 4094 and PHYSICAL.fullmatch(port):
            candidates[mac.lower(), port].add((vlan, kind.lower()))
    return {
        key: next(iter(values))[0]
        for key, values in candidates.items()
        if len({vlan for vlan, _ in values}) == 1
        and any(kind in ("dynamic", "port-access-security") for _, kind in values)
    }


async def fetch_mac_vlans(device, secret):
    from .protocols import ssh_known_hosts

    async with asyncio.timeout(30):
        async with asyncssh.connect(
            device.management_ip,
            port=device.config_port,
            username=secret["username"],
            password=secret["password"],
            known_hosts=ssh_known_hosts(device),
            client_keys=[],
            connect_timeout=5,
            login_timeout=8,
        ) as connection:
            async with connection.create_process(
                term_type="vt100", term_size=(200, 24), stderr=asyncssh.STDOUT
            ) as process:
                _, prompt = await read_prompt(process)
                process.stdin.write("no page\n")
                output, _ = await read_prompt(process, prompt=prompt)
                if CLI_ERROR.search(output):
                    raise BackupError("aruba_command")
                process.stdin.write("show mac-address-table\n")
                output, _ = await read_prompt(process, prompt=prompt, limit=2 * 1024 * 1024)
                return parse_mac_vlans(output)
