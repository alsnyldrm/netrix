"""Gateway-authoritative branching and atomically published current IP results."""

from sqlalchemy import select

from .. import models as m
from ..core import now
from .service import normalized_mac

FIELDS = (
    "hostname",
    "mac_address",
    "operating_system",
    "connected_device",
    "connected_port",
    "network",
    "connection_type",
    "power_state",
    "connection_groups",
    "connections",
    "gateway_evidence",
    "field_sources",
)


def groups(connections):
    result = {}
    for c in connections:
        g = result.setdefault(
            c["device_id"], {"device_id": c["device_id"], "device_name": c["device_name"], "ports": []}
        )
        label = c["port"] + (" " + c["aggregate"] if c.get("aggregate") else "")
        if label not in g["ports"]:
            g["ports"].append(label)
    for g in result.values():
        g["port_label"] = " - ".join(g["ports"])
    return list(result.values())


async def resolve(address, sources, progress=None):
    if getattr(sources, "nic_teaming", False):
        return await sources.resolve(progress)
    values = {
        "mac_address": "",
        "hostname": "",
        "operating_system": "",
        "connected_device": "",
        "connected_port": "",
        "network": "",
        "connection_type": "",
        "connections": [],
        "connection_groups": [],
        "gateway_evidence": [],
        "field_sources": {},
        "observations": [],
        "cached_import": False,
        "_inventory_switches_only": True,
    }
    issues, steps = [], []

    async def stage(name, operation):
        if progress:
            await progress(name)
        try:
            data = await operation()
            if name == "gateway":
                received = bool((data or {}).get("mac_address"))
            elif name == "backbone":
                evidence = data or {}
                received = bool(evidence.get("connections")) and not evidence.get("connection_ambiguous")
            else:
                received = bool(data)
            steps.append(
                {"source": name, "status": "with_data" if received else "missing", "at": now().isoformat()}
            )
            return data
        except Exception as exc:
            from ..worker import Cancelled
            from .dhcp_errors import DHCPReadError

            if isinstance(exc, Cancelled):
                raise
            code = type(exc).__name__
            detail = f"{name}: kaynak okunamadı ({code}); önceki doğrulanmış bilgiler korundu."
            if isinstance(exc, DHCPReadError):
                code = exc.public_code
                detail = exc.public_message + " Önceki doğrulanmış bilgiler korundu."
            issues.append(
                {
                    "source": name,
                    "code": code,
                    "message": detail,
                }
            )
            steps.append({"source": name, "status": "error", "at": now().isoformat()})
            return None

    def issue(source, code, message):
        issues.append({"source": source, "code": code, "message": message})

    def source_row(source, data, index=0):
        values["observations"].append(
            {
                "id": f"{source}:{index}",
                "source": source,
                "source_key": (
                    getattr(sources, "dns_source_key", "system")
                    if source == "dns"
                    else data.get("integration_id") or source
                ),
                "observed_at": now().isoformat(),
                "data": dict(data),
            }
        )

    gateway = await stage("gateway", lambda: sources.gateway(address))
    issues.extend((gateway or {}).get("issues", [])[:4])
    mac = normalized_mac((gateway or {}).get("mac_address"))
    values["mac_address"] = mac
    values["gateway_evidence"] = (gateway or {}).get("gateway_evidence", [])
    for i, g in enumerate(values["gateway_evidence"][:4]):
        source_row("gateway", g, i)
    values["field_sources"]["mac_address"] = "gateway" if mac else ""
    records = await stage("vmware", lambda: sources.vmware(address, mac))
    records = records if records is not None else None
    candidates = [
        r
        for r in records or []
        if r.get("address") == address
        or (mac and normalized_mac(r.get("mac_address")) == mac and r.get("point_match"))
    ]
    conflicting = [r for r in candidates if mac and normalized_mac(r.get("mac_address")) != mac]
    owners = {(r.get("integration_id", ""), r.get("vm_id") or r.get("host_id")) for r in candidates}
    if conflicting:
        issue("vmware", "identity_conflict", "VMware IP/NIC MAC adresi gateway MAC adresiyle uyuşmuyor.")
    if len(owners) > 1:
        issue(
            "vmware",
            "owner_conflict",
            "IP birden fazla VMware makinesinde bulundu; rastgele seçim yapılmadı.",
        )
    inspected_inventory = False
    dhcp = None
    hostname = None
    vm_candidates = [r for r in candidates if r.get("record_type") != "host"]
    host_candidates = [r for r in candidates if r.get("record_type") == "host"]
    for i, r in enumerate(candidates[:8]):
        source_row("vcenter", r, i)
    if vm_candidates:
        # A found but conflicting VM never falls through to a physical or DHCP identity.
        for source in ("backbone", "switch", "dhcp", "dns"):
            steps.append({"source": source, "status": "skipped_vm"})
        valid = [r for r in vm_candidates if normalized_mac(r.get("mac_address")) == mac] if mac else []
        nics = {}
        for r in valid:
            key = (
                r.get("integration_id"),
                r.get("vm_id") or r.get("host_id"),
                r.get("nic_key") or r.get("vmkernel_device"),
            )
            if key not in nics or r.get("address") == address:
                nics[key] = r
        valid = list(nics.values())[:32]
        if len(owners) == 1 and valid and not conflicting:
            names = {r.get("hostname", "").strip() for r in valid if r.get("hostname")}
            systems = {r.get("operating_system", "").strip() for r in valid if r.get("operating_system")}
            if len(names) == 1:
                values["hostname"] = next(iter(names))
            if len(systems) == 1:
                values["operating_system"] = next(iter(systems))
            virtual = []
            for r in valid:
                switch = r.get("dvswitch_name") or r.get("vswitch_name")
                port = r.get("dvport") or r.get("port")
                if switch and port:
                    virtual.append(
                        {
                            "device_id": r.get("dvswitch") or switch,
                            "device_name": switch,
                            "port": str(port),
                            "aggregate": "",
                            "source": "vcenter",
                            "confidence": 1.0,
                        }
                    )
            values.update(
                vm_ids=[
                    {"integration_id": r.get("integration_id"), "vm_id": r.get("vm_id")}
                    for r in valid
                    if r.get("vm_id")
                ],
                connection_type="vcenter",
                power_state=valid[0].get("power_state", ""),
                network=valid[0].get("network", ""),
                connections=virtual,
            )
            values["field_sources"].update(hostname="vcenter", operating_system="vcenter")
    elif records is not None:
        # ESXi management IPs are physical endpoints. VMware identifies the host,
        # but its virtual backing and uplink hints cannot replace this branch.
        if host_candidates:
            values["connection_type"] = "physical"
            if len(owners) == 1 and not conflicting:
                host = host_candidates[0]
                values["vmware_host"] = {
                    k: host.get(k) for k in ("host_id", "host_uuid", "hostname", "vmkernel_device")
                }
                values["physical_nics"] = host.get("physical_nics", [])[:32]
        fallback = not mac and getattr(sources, "inventory_fallback", False)

        def active_leases(rows):
            return [
                r
                for r in rows or []
                if r.get("reserved", True)
                or r.get("lease_state", "").casefold() in ("active", "activereservation")
            ]

        def mismatch(r, identity):
            return (r.get("address") == address and normalized_mac(r.get("mac_address")) != identity) or (
                normalized_mac(r.get("mac_address")) == identity and r.get("address") != address
            )

        dhcp = await stage("dhcp", lambda: sources.dhcp(address, "")) if fallback else []
        candidate_macs = {
            normalized_mac(r.get("mac_address")) for r in active_leases(dhcp) if r.get("address") == address
        }
        hint = next(iter(candidate_macs)) if gateway is not None and len(candidate_macs) == 1 else ""
        if hint:
            dhcp = await stage("dhcp", lambda: sources.dhcp(address, hint))
            leases = active_leases(dhcp)
            if not any(r.get("address") == address for r in leases) or any(mismatch(r, hint) for r in leases):
                issue("dhcp", "identity_conflict", "DHCP MAC adayı tek bir IP ile doğrulanamadı.")
                hint = ""
        elif len(candidate_macs) > 1:
            issue("dhcp", "identity_conflict", "Aynı IP için çelişkili DHCP MAC kayıtları var.")
        if mac or fallback:
            physical = await stage("backbone", lambda: sources.physical(address, mac or hint))
            inspected_inventory = physical is not None
            if physical:
                gateway_macs = {g["mac_address"] for g in physical.get("gateway_evidence", [])}
                if physical.get("connection_ambiguous") or (hint and not gateway_macs <= {hint}):
                    issue(
                        "switch",
                        "ambiguous",
                        physical.get("connection_reason") or "Switch/port ve IP kimliği tekil doğrulanamadı.",
                    )
                else:
                    connections = physical.get("connections", [])
                    if connections:
                        values.update(connections=connections, connection_type="physical")
                        # DHCP alone does not establish the endpoint. Promote
                        # the MAC only when the same VLAN's FDB proves an edge.
                        if hint and all(c["source"] == "gateway+vlan_fdb" for c in connections):
                            mac = hint
                            values["mac_address"] = mac
                            values["field_sources"]["mac_address"] = "windows_dhcp"
                            values["connections"] = [
                                {**c, "source": "windows_dhcp+vlan_fdb"} for c in connections
                            ]
                steps.extend(physical.get("steps", [])[:16])
        else:
            for source in ("backbone", "switch", "dhcp"):
                steps.append({"source": source, "status": "skipped_identity"})
        if mac and not fallback:
            dhcp = await stage("dhcp", lambda: sources.dhcp(address, mac))
        eligible = active_leases(dhcp)
        bad = [r for r in eligible if mac and mismatch(r, mac)]
        names = {
            r.get("hostname", "").strip()
            for r in eligible
            if mac
            and r.get("address") == address
            and normalized_mac(r.get("mac_address")) == mac
            and r.get("hostname")
        }
        for i, r in enumerate((dhcp or [])[:8]):
            source_row("windows_dhcp", r, i)
        hostname = await stage("dns", lambda: sources.dns(address))
        if hostname is not None:
            source_row("dns", {"hostname": hostname})
        if bad or len(names) > 1:
            values["hostname"] = "YANLIŞ-DHCP-VERİSİ"
            values["field_sources"]["hostname"] = "windows_dhcp"
            issue(
                "dhcp",
                "identity_conflict",
                "DHCP IP/MAC veya hostname kaydı gateway kimliğiyle çelişiyor. Gateway MAC: "
                + mac
                + ". DHCP: "
                + ", ".join(
                    f"{r.get('address', '')} / {normalized_mac(r.get('mac_address'))}" for r in bad[:4]
                ),
            )
        else:
            values["hostname"] = hostname or (next(iter(names)) if names else "")
            values["field_sources"]["hostname"] = "dns" if hostname else "windows_dhcp" if names else ""
    if not mac and not values["connections"] and gateway is not None:
        issue(
            "gateway",
            "identity_missing",
            "Gateway üzerinde tekil IP/MAC eşleşmesi bulunamadı; MAC tahmin edilmedi.",
        )
    if not values["hostname"] and (hostname is not None or vm_candidates):
        issue("resolution", "missing_hostname", "Hostname bilgisi bulunamadı.")
    values["connections"] = list({(c["device_id"], c["port"]): c for c in values["connections"]}.values())[
        :32
    ]
    values["connection_groups"] = groups(values["connections"])
    values["connected_device"] = " / ".join(g["device_name"] for g in values["connection_groups"])
    values["connected_port"] = " / ".join(g["port_label"] for g in values["connection_groups"])
    if not values["connections"] and (inspected_inventory or vm_candidates):
        issue(
            "resolution",
            "attachment_missing",
            "Bağlı switch ve port için yeterli doğrulanmış kaynak verisi bulunamadı.",
        )
    if vm_candidates and not values["operating_system"]:
        issue("vmware", "os_missing", "VMware işletim sistemi bilgisi bulunamadı.")
    return {
        "status": "problem" if issues else "success",
        "values": values,
        "issues": issues[:24],
        "steps": steps[:32],
        "absence_candidate": (
            gateway is not None
            and not gateway.get("mac_address")
            and records == []
            and dhcp == []
            and hostname == ""
            and inspected_inventory
            and not values["connections"]
            and not any(
                i["code"] not in ("identity_missing", "missing_hostname", "attachment_missing")
                for i in issues
            )
        ),
    }


def save_result(db, row, started, result):
    expected_scope = [row.address, row.vrf_id, row.vlan_id]
    current = db.scalar(
        select(m.IPAddress)
        .where(m.IPAddress.id == row.id)
        .with_for_update(of=m.IPAddress)
        .execution_options(populate_existing=True)
    )
    if not current or [current.address, current.vrf_id, current.vlan_id] != expected_scope:
        return False
    item = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == row.id).with_for_update())
    scope = [row.address, row.vrf_id, row.vlan_id]
    if (
        item
        and item.address_scope == scope
        and item.started_at > started
        and not item.values.get("cached_import")
    ):
        return False
    if not item:
        item = m.IPAMResult(address_id=row.id, values={})
        db.add(item)
    previous = item.values if item.address_scope == scope else {}
    incoming = result["values"]
    retained = False
    if result["status"] == "problem":
        # Never carry an attachment/hostname to a new gateway identity.
        identity_changed = (
            incoming.get("mac_address")
            and previous.get("mac_address")
            and incoming["mac_address"] != previous["mac_address"]
        )
        branch_changed = (
            incoming.get("connection_type")
            and previous.get("connection_type")
            and incoming["connection_type"] != previous["connection_type"]
        )
        if identity_changed or branch_changed:
            previous = {}
        merged = {**incoming, **previous, **{k: v for k, v in incoming.items() if v}}
        cleared = (
            {"operating_system", "network", "power_state"}
            if incoming.get("connection_type") in ("physical", "nic_teaming")
            else set()
        )
        retained = any(previous.get(k) and not incoming.get(k) for k in FIELDS if k not in cleared)
        if incoming.get("connection_type") in ("physical", "nic_teaming"):
            merged["operating_system"] = merged["network"] = merged["power_state"] = ""
        merged["cached_import"] = incoming.get("cached_import", False)
        merged["field_sources"] = {
            **previous.get("field_sources", {}),
            **{k: v for k, v in incoming.get("field_sources", {}).items() if v},
        }
    else:
        merged = incoming
    item.address_scope, item.status, item.values = scope, result["status"], merged
    item.issues, item.steps = result["issues"][:24], result["steps"][:32]
    item.retained, item.started_at, item.completed_at = retained, started, now()
    if item.status == "success":
        item.last_success_at = item.completed_at
    db.flush()
    return True


def sources_for(db, row, vlan, collector):
    from .point_sources import PointSources

    if getattr(row, "nic_teaming", False):
        from .teaming import TeamingSources

        return TeamingSources(row, vlan)
    return PointSources(db, row, vlan, collector)


def apply(item, result, *, details=True):
    """Read-only projection. Managed edits and independent ICMP remain separate."""
    from ..services import serialize

    ping = [o for o in item.get("observations", []) if o.get("source") == "icmp"]
    item.update({k: v for k, v in result.values.items() if k != "observations"})
    if details:
        item["observations"] = result.values.get("observations", []) + ping
    item["field_sources"] = dict(item.get("field_sources", {}))
    item["scan_status"] = result.status
    item["scan_result"] = {k: v for k, v in serialize(result).items() if k not in ("values", "address_scope")}
    item["connection_ambiguous"] = any(
        i["source"] != "dhcp" and i["code"] in ("ambiguous", "owner_conflict", "identity_conflict")
        for i in result.issues
    )
    attachment_issues = [
        i
        for i in result.issues
        if i["source"] in ("gateway", "switch", "backbone", "vmware") or i["code"] == "attachment_missing"
    ]
    item["connection_reason"] = "; ".join(i["message"] for i in attachment_issues) or (
        "Güncel bağlantı kanıtıyla eşleşti" if item.get("connected_device") else "Bağlantı doğrulanamadı"
    )
    item["automatic_mac_address"] = item.get("mac_address", "")
    for field in ("hostname", "mac_address", "operating_system"):
        if item["managed"].get(field):
            item[field] = item["managed"][field]
            item.setdefault("field_sources", {})[field] = "manual"
    if item.get("connection_type") == "vcenter":
        item["cabinet"] = "Sanal"
    item["sources"] = sorted(
        (
            {o["source"] for o in result.values.get("observations", [])}
            | set(item.get("field_sources", {}).values())
            | {c.get("source", "") for c in item.get("connections", [])}
            | ({"icmp"} if ping else set())
        )
        - {""}
    )
    item["last_observed_at"] = result.completed_at.isoformat()
    item["stale"] = result.retained
    return item
