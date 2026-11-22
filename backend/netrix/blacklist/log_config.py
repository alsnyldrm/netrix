"""Logging configuration added only to explicitly submitted NETRIX ACL plans."""

from ipaddress import ip_address

from .cli import ACLError


def validate_target(host, port):
    if ip_address(host).version != 4 or not 1 <= port <= 65535:
        raise ACLError("ACL log alıcı adresi/portu geçersiz.")


def configuration(adapter, host, port):
    validate_target(host, port)
    if adapter in ("aruba_5400", "aruba_2900"):
        return [f"logging {host} udp {port}"]
    if adapter == "aruba_6100":
        return [f"logging {host} udp {port} severity info"]
    if adapter == "aruba_7200":
        return [f"logging {host} dest-port {port} severity informational type security",
                "logging security subcat firewall level informational"]
    return ["info-center enable", f"info-center loghost {host} port {port}",
            "info-center source ACL channel loghost log level informational", "acl logging interval 1"]


def debug_configuration(adapter):
    if adapter in ("aruba_5400", "aruba_2900"):
        return ["debug destination logging", "debug acl"]
    if adapter == "aruba_6100":
        return ["debug destination syslog severity info", "debug acl log severity info"]
    return []


def deny(adapter, profile, sequence, address, *, logging=False):
    if adapter == "hp_1950":
        protocol = "ip " if profile["type"] == "advanced" else ""
        value = f"rule {sequence} deny {protocol}source {address} 0"
        return value + (" logging" if logging else "")
    if adapter == "aruba_6100":
        value = f"{sequence} deny any {address}/32 any"
    elif profile["type"] == "standard":
        value = f"{sequence} deny host {address}"
    else:
        value = f"{sequence} deny ip host {address} any"
    return value + (" log" if logging else "")


def logged_sequences(body):
    import re
    return {
        int(match[1]) for line in (body or [])
        if (match := re.fullmatch(r"(?:rule )?(\d+) deny .* (?:log|logging)", line))
    }


def logging_rules(adapter, profile, entries, body, address):
    """Install the logged replacement before removing its old unlogged deny."""
    used = set(entries)
    logged = logged_sequences(body)
    by_address = {}
    for sequence, existing_address in entries.items():
        by_address.setdefault(existing_address, []).append(sequence)
    by_address.setdefault(address, [])
    commands = []
    for target, sequences in by_address.items():
        if not any(sequence in logged for sequence in sequences):
            free = next((number for number in range(10, 60000) if number not in used), None)
            if free is None:
                raise ACLError("Loglu ACL kuralı için sıra alanı kalmadı.")
            used.add(free)
            commands.append(deny(adapter, profile, free, target, logging=True))
        for old in sequences:
            if old not in logged:
                commands.append(("undo rule " if adapter == "hp_1950" else "no ") + str(old))
    return commands


def verify_target(plan, parsed):
    prefix = "info-center loghost " if plan.adapter == "hp_1950" else "logging "
    candidates = [header.split() for header, _ in parsed if header.startswith(prefix)]
    if not any(plan.log_host in tokens and str(plan.log_port) in tokens for tokens in candidates):
        raise ACLError("ACL Syslog hedefi kalıcı/çalışan konfigürasyonda doğrulanamadı.")


def check_existing_target(adapter, parsed, host, port):
    prefix = "info-center loghost " if adapter == "hp_1950" else "logging "
    for header, _ in parsed:
        tokens = header.split()
        if not header.startswith(prefix) or host not in tokens:
            continue
        expected = str(port)
        if expected not in tokens:
            raise ACLError("Aynı Syslog sunucusu başka portla yapılandırılmış. Mevcut hedefi korumak için ayrı alıcı adresi veya log yönlendirmesi kullanın.")
