"""Vendor CLI plans. All targets come from a fresh device read, never user commands."""

import hashlib
import re
import shlex
from dataclasses import dataclass
from ipaddress import ip_address

from ..discovery.aruba import validate_aruba_config
from ..discovery.comware import validate_comware_config
from .cli import ACLError

MARKER = "NETRIX-BLACKLIST"
AOS_PORT = r"(?:\d+/)?[A-Za-z]?\d+(?:/\d+)*"
PERMIT_SEQUENCE = 60000


def words(line):
    try:
        return shlex.split(line)
    except ValueError:
        raise ACLError("Cihazın yapılandırma biçimi çözümlenemedi.") from None


def blocks(config):
    result, header, body = [], None, []
    for line in config.splitlines():
        if not line.strip():
            continue
        if line.strip() in ("exit", "quit", "return", "#", "!"):
            if header is not None:
                result.append((header, body))
            header, body = None, []
            continue
        if (
            header
            and header.startswith(("ip access-list session ", "netdestination "))
            and line.lstrip().startswith("Description:")
        ):
            body.append("description " + " ".join(words(line.split(":", 1)[1])))
            continue
        if line[0].isspace() and header is not None:
            body.append(" ".join(words(line)))
            continue
        if header is not None:
            result.append((header, body))
        header, body = " ".join(words(line)), []
    if header is not None:
        result.append((header, body))
    return result


def canonical_port(port):
    if re.fullmatch(r"trk\d+", port, re.I):
        return "Trk" + str(int(port[3:]))
    return port.upper()


def expand_ports(value):
    """Expand only bounded same-module ranges emitted in AOS-S configuration."""
    result = []
    for piece in value.split(","):
        if "-" not in piece:
            if not re.fullmatch("(?:" + AOS_PORT + r"|Trk\d+)", piece, re.I):
                raise ACLError("Port listesi doğrulanamadı.")
            result.append(piece)
            continue
        start, end = piece.split("-", 1)
        a, b = re.fullmatch(r"(.*?)(\d+)", start), re.fullmatch(r"(.*?)(\d+)", end)
        if not a or not b or (b[1] and a[1] != b[1]) or not 0 <= int(b[2]) - int(a[2]) <= 512:
            raise ACLError("Port aralığı doğrulanamadı.")
        result.extend(a[1] + str(number) for number in range(int(a[2]), int(b[2]) + 1))
    return [canonical_port(port) for port in result]


def port_inventory(adapter, output, config_blocks):
    physical = set()
    annotations = {}
    if adapter in ("aruba_5400", "aruba_2900"):
        if not re.search(r"Port.*(?:Type|Status)", output, re.I):
            raise ACLError("Tüm fiziksel portların listesi okunamadı.")
        for port, trunk in re.findall(
            r"(?mi)^\s*(" + AOS_PORT + r")(?:-(Trk\d+))?\s+[^\n]*\|", output
        ):
            port = canonical_port(port)
            physical.add(port)
            if trunk:
                annotations[port] = canonical_port(trunk)
    elif adapter == "aruba_6100":
        if not re.search(r"(?:Port|Interface)", output, re.I):
            raise ACLError("Tüm fiziksel portların listesi okunamadı.")
        physical = set(re.findall(r"(?m)^\s*(\d+/\d+/\d+)\s+\S+", output))
    elif adapter == "aruba_7200":
        physical = {
            "gigabitethernet " + p
            for p in re.findall(r"(?im)^\s*(?:GE|GigabitEthernet)\s*(\d+/\d+/\d+)(?:\s|\s+is\s)", output)
        }
    else:
        prefixes = {
            "GE": "GigabitEthernet",
            "XGE": "Ten-GigabitEthernet",
            "GigabitEthernet": "GigabitEthernet",
            "Ten-GigabitEthernet": "Ten-GigabitEthernet",
        }
        for prefix, port in re.findall(
            r"(?m)^\s*(GE|XGE|GigabitEthernet|Ten-GigabitEthernet)(\d+/\d+/\d+)\s+\S+", output
        ):
            physical.add(prefixes[prefix] + port)
    if not physical or len(physical) > 4096:
        raise ACLError("Tüm fiziksel portların listesi doğrulanamadı; ACL uygulanmadı.")

    members, aggregates, interface_blocks = config_interfaces(adapter, config_blocks)
    if annotations:
        configured = {}
        for header, _ in config_blocks:
            if header.startswith("trunk "):
                parts = words(header)
                for member in expand_ports(parts[1]):
                    configured[member] = canonical_port(parts[2])
        if any(configured.get(port) != trunk for port, trunk in annotations.items()):
            raise ACLError("Port tablosu ile yapılandırmadaki LAG üyeliği çelişiyor.")
    if not members <= physical:
        raise ACLError("LAG üyeleri ile fiziksel port listesi tutarsız.")
    targets = sorted((physical - members) | aggregates)
    return targets, interface_blocks, sorted(physical)


def config_interfaces(adapter, config_blocks):
    """Interface blocks and LAG membership read from configuration only."""
    members, aggregates, interface_blocks = set(), set(), {}
    for header, body in config_blocks:
        if header.startswith("trunk ") and adapter in ("aruba_5400", "aruba_2900"):
            parts = words(header)
            if len(parts) < 3 or not re.fullmatch(r"Trk\d+", parts[2], re.I):
                raise ACLError("Trunk üyeliği doğrulanamadı.")
            members.update(expand_ports(parts[1]))
            aggregates.add(canonical_port(parts[2]))
        if not header.startswith("interface "):
            continue
        port = header.removeprefix("interface ")
        if adapter in ("aruba_5400", "aruba_2900"):
            if port.startswith(("loopback ", "tunnel ")):
                continue
            ports = expand_ports(port)
        else:
            ports = [port]
        for name in ports:
            interface_blocks[name] = body
            if adapter == "aruba_6100" and re.fullmatch(r"\d+/\d+/\d+", name):
                for line in body:
                    if re.fullmatch(r"lag \d+", line):
                        members.add(name)
                        aggregates.add(line)
            if adapter == "hp_1950":
                for line in body:
                    match = re.fullmatch(r"port link-aggregation group (\d+)", line)
                    if match:
                        members.add(name)
                        aggregates.add("Bridge-Aggregation" + match[1])
            if adapter == "aruba_7200" and re.fullmatch(r"port-channel \d+", name):
                aggregates.add(name)
                for line in body:
                    if re.fullmatch(r"gigabitethernet \d+/\d+/\d+", line):
                        members.add(line)
    return members, aggregates, interface_blocks


@dataclass
class Plan:
    commands: list[str]
    ports: list[str]
    physical_ports: list[str]
    acl_header: str
    bind: str
    address: str
    profile: dict
    adapter: str
    alias: str = ""
    addresses: tuple = ()
    added: tuple = ()
    removed: tuple = ()
    removal: bool = False


def acl_identity(adapter, profile):
    name = profile["name"] or str(profile["number"])
    if adapter in ("aruba_5400", "aruba_2900"):
        return f"ip access-list {profile['type']} {name}", f"ip access-group {name} in"
    if adapter == "aruba_6100":
        return f"access-list ip {name}", f"apply access-list ip {name} in"
    if adapter == "aruba_7200":
        return f"ip access-list session {name}", f"ip access-group in {name}"
    suffix = (" name " + profile["name"]) if profile["name"] else ""
    return f"acl number {profile['number']}{suffix}", f"packet-filter {profile['number']} inbound"


def matching_acl(config_blocks, header, adapter):
    matches = []
    for actual, body in config_blocks:
        if actual == header:
            matches.append(body)
        elif adapter == "hp_1950" and re.sub(r"^acl (?:basic|advanced) ", "acl number ", actual) == header:
            matches.append(body)
    if len(matches) > 1:
        raise ACLError("Aynı ACL için birden fazla yapılandırma bloğu bulundu.")
    return matches[0] if matches else None


def rules(adapter, profile, body):
    """Accept only the bounded deny-host and final permit rules owned by NETRIX."""
    if body is None:
        return {}, False
    if not any(re.fullmatch(r"(?:60000 )?(?:remark|comment|description) " + MARKER, line) for line in body):
        raise ACLError("ACL kimliği cihazda başka bir yapılandırmaya ait. Farklı ad/numara seçin.")
    entries, permit = {}, False
    for line in body:
        if MARKER in line and re.fullmatch(r"(?:60000 )?(?:remark|comment|description) " + MARKER, line):
            continue
        if line == "step 5":
            continue
        if adapter in ("aruba_5400", "aruba_2900"):
            permit_line = "60000 permit any" if profile["type"] == "standard" else "60000 permit ip any any"
            pattern = (
                r"(\d+) deny (?:host )?(\S+)(?: 0\.0\.0\.0)?"
                if profile["type"] == "standard"
                else r"(\d+) deny ip (?:host )?(\S+)(?: 0\.0\.0\.0)? (?:any|0\.0\.0\.0 255\.255\.255\.255)"
            )
        elif adapter == "aruba_6100":
            permit_line = "60000 permit any any any"
            pattern = r"(\d+) deny (?:any|ip) (\d+\.\d+\.\d+\.\d+)(?:/(?:32|255\.255\.255\.255))? any"
        else:
            permit_line = "rule 60000 permit" if profile["type"] == "basic" else "rule 60000 permit ip"
            pattern = (
                r"rule (\d+) deny source (\S+) (?:0|0\.0\.0\.0)"
                if profile["type"] == "basic"
                else r"rule (\d+) deny ip source (\S+) (?:0|0\.0\.0\.0)"
            )
        # AOS-S may render wildcard forms even when the CLI used "any".
        numeric_permit = permit_line.replace("any", "0.0.0.0 255.255.255.255")
        if line in (permit_line, numeric_permit) or (
            adapter == "aruba_6100" and line == "60000 permit ip any any"
        ):
            permit = True
            continue
        match = re.fullmatch(pattern, re.sub(r" (?:log|logging)$", "", line))
        if not match or not 0 <= int(match[1]) < PERMIT_SEQUENCE or int(match[1]) in entries:
            raise ACLError("NETRIX ACL içeriği değiştirilmiş veya kural sırası belirsiz; işlem durdu.")
        try:
            address = ip_address(match[2])
            if address.version != 4:
                raise ValueError()
        except ValueError:
            raise ACLError("ACL içinde geçersiz adres bulundu.") from None
        entries[int(match[1])] = str(address)
    return entries, permit


def session_rules(config_blocks, header, alias):
    body = matching_acl(config_blocks, header, "aruba_7200")
    if body is not None:
        allowed = {f"description {MARKER}", f"alias {alias} any any deny", f"alias {alias} any any deny log", "any any any permit"}
        if f"description {MARKER}" not in body or any(line not in allowed for line in body):
            raise ACLError("Session ACL başka bir yapılandırmaya ait veya değiştirilmiş.")
    alias_body = matching_acl(config_blocks, "netdestination " + alias, "aruba_7200")
    hosts = set()
    if alias_body is not None:
        if f"description {MARKER}" not in alias_body:
            raise ACLError("Controller adres nesnesi başka bir yapılandırmaya ait.")
        for line in alias_body:
            if line == f"description {MARKER}":
                continue
            match = re.fullmatch(r"host (\d+\.\d+\.\d+\.\d+)(?: position \d+)?", line)
            if not match:
                raise ACLError("Controller adres nesnesi değiştirilmiş.")
            hosts.add(str(ip_address(match[1])))
    return body, hosts


def undo(adapter, line):
    if adapter == "aruba_7200" and line.startswith("ip access-group in "):
        return "no ip access-group in"
    if adapter == "hp_1950":
        # Comware deletes an ACL by number; the optional name is not part of the key.
        return "undo " + re.sub(r"^(acl number \d+) name \S+$", r"\1", line)
    return "no " + line


def validate_config(adapter, config):
    if adapter == "hp_1950":
        validate_comware_config(config)
    elif adapter != "aruba_7200":
        validate_aruba_config(adapter, config)
    elif not re.search(r"(?m)^hostname\s+\S+", config):
        raise ACLError("Controller yapılandırması eksik okundu.")


def alias_for(header):
    return "nxbl_" + hashlib.sha256(header.encode()).hexdigest()[:16]


def canonical_addresses(addresses):
    result = set()
    for address in addresses:
        value = ip_address(address)
        if value.version != 4:
            raise ACLError("Bu gönderim IPv4 içindir. IPv6 ACL gönderimi desteklenmiyor.")
        result.add(str(value))
    return result


def build_removal_plan(adapter, profile, config, *, validated=False):
    """Remove the NETRIX ACL, its port bindings and the controller alias. Foreign ACLs stop the plan."""
    if not validated:
        validate_config(adapter, config)
    parsed = blocks(config)
    _, _, interface_blocks = config_interfaces(adapter, parsed)
    header, bind = acl_identity(adapter, profile)
    alias = alias_for(header) if adapter == "aruba_7200" else ""
    if adapter == "aruba_7200":
        body, hosts = session_rules(parsed, header, alias)
        alias_present = matching_acl(parsed, "netdestination " + alias, adapter) is not None
    else:
        body = matching_acl(parsed, header, adapter)
        hosts = set(rules(adapter, profile, body)[0].values())
        alias_present = False
    bound = sorted(port for port, lines in interface_blocks.items() if bind in lines)
    if body is None and bound:
        raise ACLError("Portlarda NETRIX ACL bağlantısı var ancak ACL tanımı bulunamadı; işlem durduruldu.")
    commands = []
    end = "quit" if adapter == "hp_1950" else "exit"
    for port in bound:
        commands += ["interface " + port, undo(adapter, bind), end]
    if body is not None:
        commands.append(undo(adapter, header))
    if alias_present:
        commands.append("no netdestination " + alias)
    if commands:
        commands = ["system-view" if adapter == "hp_1950" else "configure terminal", *commands]
        commands.append("return" if adapter == "hp_1950" else "end")
    return Plan(
        commands, bound, [], header, bind, "", profile, adapter, alias,
        removed=tuple(sorted(hosts)), removal=True,
    )


def deny(adapter, profile, sequence, address):
    if adapter == "hp_1950":
        protocol = "ip " if profile["type"] == "advanced" else ""
        return f"rule {sequence} deny {protocol}source {address} 0"
    if adapter == "aruba_6100":
        return f"{sequence} deny any {address}/32 any"
    if profile["type"] == "standard":
        return f"{sequence} deny host {address}"
    return f"{sequence} deny ip host {address} any"


def build_plan(adapter, profile, address, config, ports_output):
    """Add one address and keep every NETRIX address already present."""
    return build_sync_plan(adapter, profile, {address}, config, ports_output, keep=True)


def build_sync_plan(adapter, profile, desired, config, ports_output, *, keep=False, retain_empty=False, validated=False):
    """Make the NETRIX ACL contain exactly the desired addresses on every port.

    With retain_empty=True an empty set retains a permit-only ACL; otherwise it removes the ACL and its bindings. With keep=True the
    current NETRIX addresses are preserved and only missing ones are added.
    """
    desired = canonical_addresses(desired)
    if not validated:
        validate_config(adapter, config)
    if not desired and not keep and not retain_empty:
        return build_removal_plan(adapter, profile, config, validated=True)
    parsed = blocks(config)
    ports, port_blocks, physical = port_inventory(adapter, ports_output, parsed)
    header, bind = acl_identity(adapter, profile)
    # Preflight every target, including LAG member interfaces, before the first write.
    for port in set(ports) | set(physical):
        for line in port_blocks.get(port, []):
            if line.startswith(("ip access-group ", "apply access-list ip ", "packet-filter ")):
                if line != bind:
                    raise ACLError(
                        f"{port} portunda başka ACL var; mevcut politika korunarak işlem durduruldu."
                    )
    commands = ["system-view" if adapter == "hp_1950" else "configure terminal"]
    alias = ""
    if adapter == "aruba_7200":
        alias = alias_for(header)
        body, hosts = session_rules(parsed, header, alias)
        target = desired | hosts if keep else desired
        if target:
            commands += ["netdestination " + alias, "description " + MARKER]
            commands += ["host " + address for address in sorted(target - hosts)]
            commands += ["no host " + address for address in sorted(hosts - target)]
            commands.append("exit")
        commands += [header, "description " + MARKER]
        if target and (body is None or not any(line.startswith(f"alias {alias} any any deny") for line in body)):
            commands.append(f"alias {alias} any any deny" + (" position 1" if body and "any any any permit" in body else ""))
        if body is None or "any any any permit" not in body:
            commands.append("any any any permit")
        commands.append("exit")
        present = hosts
    else:
        body = matching_acl(parsed, header, adapter)
        entries, permit = rules(adapter, profile, body)
        present = set(entries.values())
        target = desired | present if keep else desired
        if adapter == "hp_1950":
            marker, permit_line = "description " + MARKER, "rule 60000 permit"
            if profile["type"] == "advanced":
                permit_line += " ip"
        elif adapter == "aruba_6100":
            marker, permit_line = "60000 comment " + MARKER, "60000 permit any any any"
        else:
            marker, permit_line = "60000 remark " + MARKER, "60000 permit any"
            if profile["type"] == "extended":
                permit_line = "60000 permit ip any any"
        commands += [header, marker]
        used = set(entries)
        for address in sorted(target - present):
            sequence = next((n for n in range(10, PERMIT_SEQUENCE) if n not in used), None)
            if sequence is None:
                raise ACLError("NETRIX ACL sıra alanı doldu.")
            used.add(sequence)
            commands.append(deny(adapter, profile, sequence, address))
        kept = set()
        for sequence, address in sorted(entries.items()):
            # Extra addresses and duplicate rules of one address are removed.
            if address not in target or address in kept:
                commands.append(("undo rule " if adapter == "hp_1950" else "no ") + str(sequence))
            kept.add(address)
        if not permit:
            commands.append(permit_line)
        commands.append("quit" if adapter == "hp_1950" else "exit")
    for port in ports:
        if bind not in port_blocks.get(port, []):
            commands += ["interface " + port, bind, "quit" if adapter == "hp_1950" else "exit"]
    commands.append("return" if adapter == "hp_1950" else "end")
    first = min(desired, key=lambda value: ip_address(value)) if desired else ""
    return Plan(
        commands, ports, physical, header, bind, first, profile, adapter, alias,
        addresses=tuple(sorted(target, key=ip_address)),
        added=tuple(sorted(target - present, key=ip_address)),
        removed=tuple(sorted(present - target, key=ip_address)),
    )


def verify_removed(plan, config):
    parsed = blocks(config)
    _, _, interface_blocks = config_interfaces(plan.adapter, parsed)
    if any(plan.bind in lines for lines in interface_blocks.values()):
        raise ACLError("NETRIX ACL bazı portlardan kaldırılamadı; sonuç kısmi olabilir.")
    if matching_acl(parsed, plan.acl_header, plan.adapter) is not None:
        raise ACLError("NETRIX ACL tanımı cihazdan kaldırılamadı.")
    if plan.alias and matching_acl(parsed, "netdestination " + plan.alias, plan.adapter) is not None:
        raise ACLError("Controller adres nesnesi kaldırılamadı.")


def verify(plan, config, ports_output):
    if plan.removal:
        return verify_removed(plan, config)
    parsed = blocks(config)
    ports, port_blocks, physical = port_inventory(plan.adapter, ports_output, parsed)
    if ports != plan.ports or physical != plan.physical_ports:
        raise ACLError("İşlem sırasında port üyeliği değişti; tüm portlar doğrulanamadı.")
    if any(plan.bind not in port_blocks.get(port, []) for port in ports):
        raise ACLError(
            "ACL tüm portlarda doğrulanamadı; sonuç kısmi olabilir. Yeniden göndererek doğrulayın."
        )
    expected = set(plan.addresses)
    if plan.adapter == "aruba_7200":
        body, hosts = session_rules(parsed, plan.acl_header, plan.alias)
        if (not body or hosts != expected or body[-1] != "any any any permit"
                or (expected and f"alias {plan.alias} any any deny" not in body)
                or (not expected and any(" deny" in line for line in body))):
            raise ACLError("Controller deny/izin sırası doğrulanamadı.")
    else:
        body = matching_acl(parsed, plan.acl_header, plan.adapter)
        entries, permit = rules(plan.adapter, plan.profile, body)
        if set(entries.values()) != expected or len(entries) != len(expected) or not permit:
            raise ACLError("Deny listesi ve son izin kuralı doğrulanamadı.")
