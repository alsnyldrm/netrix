"""Read the AOS-S forwarding table with explicit VLAN and port labels."""

import asyncio
import re

import asyncssh

from ..configuration.validation import BackupError
from .aruba import CLI_ERROR, read_prompt

HEADER = re.compile(r"^\s*MAC Address[ \t]+Port[ \t]+VLAN[ \t]*$", re.I | re.M)
ROW = re.compile(r"([0-9a-f:-]{12,17})\s+(\S+)\s+(\d+)", re.I)


def parse_mac_table(output):
    from ..ipam.service import normalized_mac

    header = HEADER.search(output)
    if not header or CLI_ERROR.search(output):
        raise BackupError("aruba_mac_table_incomplete")
    lines = output[header.end():].strip().splitlines()
    if not lines or not re.fullmatch(r"[-\s]+", lines[0]):
        raise BackupError("aruba_mac_table_incomplete")
    rows = set()
    for line in lines[1:]:
        if not line.strip():
            continue
        match = ROW.fullmatch(line.strip())
        if not match:
            raise BackupError("aruba_mac_table_incomplete")
        raw_mac, port, vlan = match.groups()
        mac, vid = normalized_mac(raw_mac), int(vlan)
        if not mac or not 1 <= vid <= 4094:
            raise BackupError("aruba_mac_table_incomplete")
        rows.add((vid, mac, port))
    return rows


async def fetch_mac_table(device, secret):
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
                process.stdin.write("show mac-address\n")
                output, _ = await read_prompt(process, prompt=prompt, limit=2 * 1024 * 1024)
                return parse_mac_table(output)
