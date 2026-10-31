"""Count and stream authorized targets without expanding entire IPv4 networks."""

import ipaddress
from dataclasses import dataclass

from .protocols import NetworkError


@dataclass(frozen=True)
class IPv4Targets:
    # Inclusive integer intervals; memory depends on exclusions, not host count.
    ranges: tuple[tuple[int, int], ...]

    def __len__(self):
        return sum(end - start + 1 for start, end in self.ranges)

    def __iter__(self):
        for start, end in self.ranges:
            for value in range(start, end + 1):
                yield str(ipaddress.IPv4Address(value))


def scope_targets(scope):
    network = ipaddress.ip_network(scope.cidr)
    if network.version == 6 and not scope.seeds:
        raise NetworkError("IPv6 için açık hedef listesi gerekli")
    if not scope.enabled:
        return []
    exclusions = [ipaddress.ip_network(value) for value in scope.exclusions]
    if scope.seeds:
        return [
            str(ip)
            for value in dict.fromkeys(scope.seeds)
            if (ip := ipaddress.ip_address(value)) in network
            and not any(ip in excluded for excluded in exclusions)
            and not (ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_unspecified)
        ]
    # /31 and /32 include both endpoints, as IPv4Network.hosts() does.
    offset = 1 if network.prefixlen < 31 else 0
    ranges = [(int(network.network_address) + offset, int(network.broadcast_address) - offset)]
    exclusions += [
        ipaddress.ip_network(value)
        for value in (
            "224.0.0.0/4",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "0.0.0.0/32",
        )
    ]
    for excluded in exclusions:
        if excluded.version != 4:
            continue
        low, high = int(excluded.network_address), int(excluded.broadcast_address)
        remaining = []
        for start, end in ranges:
            if high < start or low > end:
                remaining.append((start, end))
            else:
                if start < low:
                    remaining.append((start, low - 1))
                if high < end:
                    remaining.append((high + 1, end))
        ranges = remaining
    return IPv4Targets(tuple(ranges))
