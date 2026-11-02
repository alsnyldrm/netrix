"""Host-only demultiplexer when an existing PXE service owns UDP/69.

Only IPv4 TFTP RRQs beginning with NETRIX's exact generated filename prefix
are directed to the NETRIX container. Other TFTP traffic/rules are untouched.
Run as root after Compose, or via the supplied systemd timer. No credentials.
"""

import argparse
import ipaddress
import json
import subprocess

CHAIN = "NETRIX_FW_TFTP"


def run(*args, check=True):
    return subprocess.run(list(args), check=check, capture_output=True, text=True)


def configure(host):
    address = ipaddress.IPv4Address(host)
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        raise ValueError("A private host LAN address is required")
    container = json.loads(run("docker", "inspect", "netrix").stdout)[0]
    if not container["State"]["Running"]:
        raise RuntimeError("NETRIX container is not running")
    addresses = [v["IPAddress"] for v in container["NetworkSettings"]["Networks"].values() if v["IPAddress"]]
    if len(addresses) != 1:
        raise RuntimeError("Expected exactly one NETRIX bridge network")
    target = str(ipaddress.IPv4Address(addresses[0])) + ":1069"
    run("iptables", "-w", "-t", "nat", "-N", CHAIN, check=False)
    rule = ["-p", "udp", "-j", "DNAT", "--to-destination", target]
    if run("iptables", "-w", "-t", "nat", "-C", CHAIN, *rule, check=False).returncode:
        existing = run("iptables", "-w", "-t", "nat", "-S", CHAIN).stdout
        if "-A " in existing:
            run("iptables", "-w", "-t", "nat", "-R", CHAIN, "1", *rule)
        else:
            run("iptables", "-w", "-t", "nat", "-A", CHAIN, *rule)
    # RRQ opcode 00 01 followed immediately by ASCII 'netrix-fw-'.
    hook = [
        "-d",
        str(address),
        "-p",
        "udp",
        "--dport",
        "69",
        "-m",
        "string",
        "--algo",
        "bm",
        "--from",
        "28",
        "--to",
        "96",
        "--hex-string",
        "|00016e65747269782d66772d|",
        "-j",
        CHAIN,
    ]
    if run("iptables", "-w", "-t", "nat", "-C", "PREROUTING", *hook, check=False).returncode:
        run("iptables", "-w", "-t", "nat", "-I", "PREROUTING", "1", *hook)
    print("NETRIX firmware TFTP dispatch verified; other TFTP traffic unchanged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    configure(parser.parse_args().host)
