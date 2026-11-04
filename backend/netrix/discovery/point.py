"""Exact IP/MAC SNMP lookups. Never walk ARP, FDB or the device inventory."""

import asyncio
import ipaddress
from contextlib import asynccontextmanager

from . import protocols as p


class Reader:
    def __init__(self, engine, auth, target):
        self.engine, self.auth, self.target = engine, auth, target

    async def get(self, oids):
        error, status, _, values = await p.get_cmd(
            self.engine,
            self.auth,
            self.target,
            p.ContextData(),
            *[p.ObjectType(p.ObjectIdentity(o)) for o in oids],
            lookupMib=False,
        )
        if error or status:
            raise p.NetworkError("Point SNMP query failed")
        return {
            str(v[0]): v[1]
            for v in values
            if not isinstance(v[1], (p.NoSuchObject, p.NoSuchInstance, p.EndOfMibView))
        }

    async def metadata(self, oid, limit=4096):
        rows = {}
        async for error, status, _, values in p.bulk_walk_cmd(
            self.engine,
            self.auth,
            self.target,
            p.ContextData(),
            0,
            25,
            p.ObjectType(p.ObjectIdentity(oid)),
            lexicographicMode=False,
            lookupMib=False,
        ):
            if error or status:
                raise p.NetworkError("Point metadata query failed")
            for key, value in values:
                key = str(key)
                if key.startswith(oid + ".") and not isinstance(
                    value, (p.NoSuchObject, p.NoSuchInstance, p.EndOfMibView)
                ):
                    rows[key[len(oid) + 1 :]] = str(value)
            if len(rows) > limit:
                raise p.NetworkError("Point metadata limit exceeded")
        return rows


@asynccontextmanager
async def reader(host, port, secret):
    engine = p.SnmpEngine()
    try:
        if secret.get("protocol") == "snmpv2c":
            auth = p.CommunityData(secret["community"], mpModel=1)
        else:
            auth = p.UsmUserData(
                secret["username"],
                secret["auth_key"],
                secret["priv_key"],
                authProtocol=p.usmHMAC192SHA256AuthProtocol
                if secret.get("auth_protocol", "sha256") == "sha256"
                else p.usmHMACSHAAuthProtocol,
                privProtocol=p.usmAesCfb128Protocol,
            )
        transport = p.Udp6TransportTarget if ipaddress.ip_address(host).version == 6 else p.UdpTransportTarget
        target = await transport.create((host, port), timeout=1, retries=0)
        async with asyncio.timeout(8):
            yield Reader(engine, auth, target)
    finally:
        engine.close_dispatcher()


async def gateway(host, port, secret, address, indexes):
    ip = ipaddress.ip_address(address)
    network = indexes.get("network") if isinstance(indexes, dict) else None
    indexes = indexes.get("indexes", []) if isinstance(indexes, dict) else indexes
    if not indexes:
        from ..ipam.connections import gateway_interfaces

        async with reader(host, port, secret) as query:
            keys = (
                ("ip_addr_ifindex", "ip_addr_mask")
                if ip.version == 4
                else ("ip_address_ifindex", "ip_address_prefix")
            )
            tables = {key: await query.metadata(p.IPAM_TABLES[key]) for key in keys}
        indexes = gateway_interfaces(tables, ipaddress.ip_network(network))
    if not indexes:
        raise p.NetworkError("No directly attached gateway interface")
    oids = {}
    for index in sorted(indexes)[:16]:
        suffix = str(index) + "." + ("" if ip.version == 4 else "2.16.") + ".".join(str(b) for b in ip.packed)
        kind = "arp" if ip.version == 4 else "ndp"
        oids[p.IPAM_TABLES[kind + "_mac"] + "." + suffix] = ("mac", index)
        oids[p.IPAM_TABLES[kind + "_type"] + "." + suffix] = ("type", index)
        if ip.version == 6:
            oids[p.IPAM_TABLES["ndp_state"] + "." + suffix] = ("state", index)
    async with reader(host, port, secret) as query:
        values = await query.get(oids)
    states = {}
    for oid, value in values.items():
        key, index = oids[oid]
        states.setdefault(index, {})[key] = p.mac(value) if key == "mac" else str(value)
    return [
        v["mac"]
        for v in states.values()
        if v.get("mac") and v.get("type") not in ("1", "2") and v.get("state") not in ("5", "6", "7")
    ]


async def switch(host, port, secret, mac, vid, hint):
    """GET only the requested (FID,MAC); metadata contains no other MAC records."""
    from .neighbors import local_port, parse_neighbors

    tables = hint.get("tables", {})
    suffix = ".".join(str(int(b, 16)) for b in mac.split(":"))
    async with reader(host, port, secret) as query:
        # Read current VLAN->FID metadata: cached FID alone may have changed.
        mapping = await query.metadata(p.IPAM_TABLES["vlan_fdb_id"])
        fids = {v for k, v in mapping.items() if k.split(".")[-1] == str(vid)}
        if len(fids) != 1 or any(
            v == fid and k.split(".")[-1] != str(vid) for fid in fids for k, v in mapping.items()
        ):
            return {"ports": [], "neighbors": []}
        fid = next(iter(fids))
        index = fid + "." + suffix
        portoid = p.IPAM_TABLES["vlan_fdb_port"] + "." + index
        statusoid = p.IPAM_TABLES["vlan_fdb_status"] + "." + index
        values = await query.get([portoid, statusoid])
        if str(values.get(statusoid)) not in ("1", "3", "5"):
            return {"ports": [], "neighbors": []}
        bridge = p.number(values.get(portoid))
        if not bridge or not 1 <= bridge <= 65535:
            return {"ports": [], "neighbors": []}
        oid = p.IPAM_TABLES["bridge_ifindex"] + "." + str(bridge)
        ifindex = p.number((await query.get([oid])).get(oid))
        if not ifindex:
            return {"ports": [], "neighbors": []}
        nameoid = p.IPAM_TABLES["if_name"] + "." + str(ifindex)
        upoid = p.IPAM_TABLES["if_status"] + "." + str(ifindex)
        values = await query.get([nameoid, upoid])
        name = str(values.get(nameoid) or "")
        if not name or str(values.get(upoid)) != "1":
            return {"ports": [], "neighbors": []}
        # Cached local-index metadata locates exact LLDP/CDP rows; re-read their identities.
        exact = {}
        for key, base in p.IPAM_TABLES.items():
            if not key.startswith(("lldp_", "cdp_")) or "local" in key:
                continue
            for index in tables.get(key, {}):
                parts = index.split(".")
                local = (
                    local_port(tables, parts[1])
                    if key.startswith("lldp_") and len(parts) == 3
                    else str(tables.get("if_name", {}).get(parts[0], ""))
                )
                if local == name:
                    exact[base + "." + index] = (key, index)
        current = {
            k: dict(v)
            for k, v in tables.items()
            if k.startswith("lldp_local") or k in ("if_name", "if_descr", "if_alias", "if_mac")
        }
        if exact:
            for oid, value in (await query.get(exact)).items():
                key, index = exact[oid]
                current.setdefault(key, {})[index] = value
        neighbors = parse_neighbors(current)
        return {"ports": [{"port": name, "if_index": ifindex}], "neighbors": neighbors}
