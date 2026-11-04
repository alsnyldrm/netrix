"""Read-only integration adapters. No API request performs these network calls."""

import asyncio
import base64
import ipaddress
import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

from ..discovery.protocols import NetworkError
from .service import normalized_mac

DHCP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Import-Module DhcpServer -ErrorAction Stop
$rows = @(Get-DhcpServerv4Scope -ErrorAction Stop | ForEach-Object {
    Get-DhcpServerv4Reservation -ScopeId $_.ScopeId -ErrorAction Stop | ForEach-Object {
        [PSCustomObject]@{address=$_.IPAddress.IPAddressToString; mac_address=[string]$_.ClientId; hostname=[string]$_.Name; reserved=$true}
    }
    Get-DhcpServerv4Lease -ScopeId $_.ScopeId -ErrorAction Stop | ForEach-Object {
        [PSCustomObject]@{address=$_.IPAddress.IPAddressToString; mac_address=[string]$_.ClientId; hostname=[string]$_.HostName; reserved=$false; lease_state=[string]$_.AddressState}
    }
})
ConvertTo-Json -InputObject $rows -Compress -Depth 4
"""


def dhcp_records(content, *, preserve_conflicts=False):
    rows = json.loads(content.decode("utf-8-sig"))
    if not isinstance(rows, list) or len(rows) > 100000:
        raise NetworkError("Invalid DHCP response")
    result = {}
    for row in rows:
        address = str(ipaddress.ip_address(row["address"]))
        key = (address, normalized_mac(row.get("mac_address"))) if preserve_conflicts else address
        if key in result and result[key]["reserved"]:
            continue
        result[key] = {
            "address": str(ipaddress.ip_address(row["address"])),
            "mac_address": normalized_mac(row.get("mac_address")),
            "hostname": str(row.get("hostname") or "")[:190],
            "reserved": row.get("reserved", True) is not False,
            "lease_state": str(row.get("lease_state") or "")[:40],
        }
    return list(result.values())


def windows_dhcp(config, secret, *, script=None, point=False, preserve_conflicts=False):
    import winrm

    host = f"[{config.host}]" if ":" in config.host else config.host
    session = winrm.Session(
        f"https://{host}:{config.port}/wsman",
        auth=(secret["username"], secret["password"]),
        transport="ntlm",
        server_cert_validation="validate" if config.verify_tls else "ignore",
        operation_timeout_sec=5 if point else 20,
        read_timeout_sec=10 if point else 25,
    )
    from winrm.exceptions import WinRMOperationTimeoutError

    protocol = session.protocol
    shell_id = protocol.open_shell()
    command_id = None
    try:
        encoded = base64.b64encode((script or DHCP_SCRIPT).encode("utf-16-le")).decode("ascii")
        command_id = protocol.run_command(
            shell_id, "powershell.exe", ["-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
        )
        deadline, output = time.monotonic() + (15 if point else 240), bytearray()
        while time.monotonic() < deadline:
            try:
                stdout, _, status, done = protocol.get_command_output_raw(shell_id, command_id)
            except WinRMOperationTimeoutError:
                continue
            output.extend(stdout)
            if len(output) > 32 * 1024 * 1024:
                raise NetworkError("DHCP response size limit exceeded")
            if done:
                if status:
                    raise NetworkError("Windows DHCP read failed")
                return dhcp_records(bytes(output), preserve_conflicts=preserve_conflicts)
        raise NetworkError("Windows DHCP read timeout")
    finally:
        if command_id:
            with suppress(Exception):
                protocol.cleanup_command(shell_id, command_id)
        with suppress(Exception):
            protocol.close_shell(shell_id)


def connect_vcenter(config, secret):
    from pyVim.connect import SmartConnect

    context = ssl.create_default_context()
    if not config.verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return SmartConnect(
        host=config.host,
        port=config.port,
        user=secret["username"],
        pwd=secret["password"],
        sslContext=context,
        httpConnectionTimeout=15,
    )


def vm_records(vm_id, values, networks=None):
    from pyVmomi import vim

    networks = networks or {"switches": {}, "portgroups": {}, "hosts": {}}
    guest, devices = values.get("guest"), values.get("config.hardware.device") or []
    nics = {d.key: d for d in devices if isinstance(d, vim.vm.device.VirtualEthernetCard)}
    result = []
    guest_nics = {n.deviceConfigId: n for n in getattr(guest, "net", None) or []}
    for key in set(nics) | set(guest_nics):
        hardware, nic = nics.get(key), guest_nics.get(key)
        backing = getattr(hardware, "backing", None)
        dvport = getattr(backing, "port", None)
        switch_uuid = getattr(dvport, "switchUuid", "") or ""
        group_key = getattr(dvport, "portgroupKey", "") or ""
        host_id = getattr(values.get("runtime.host"), "_moId", "")
        host = networks["hosts"].get(host_id, {})
        network = (
            networks["portgroups"].get((switch_uuid, group_key))
            or getattr(backing, "deviceName", "")
            or getattr(nic, "network", "")
            or ""
        )
        ips = [v.ipAddress for v in (getattr(getattr(nic, "ipConfig", None), "ipAddress", None) or [])]
        ips = ips or getattr(nic, "ipAddress", None) or [""]
        for address in ips:
            if address:
                try:
                    address = str(ipaddress.ip_address(address))
                except ValueError:
                    continue
            result.append(
                {
                    "address": address,
                    "mac_address": normalized_mac(getattr(hardware, "macAddress", ""))
                    or normalized_mac(getattr(nic, "macAddress", "")),
                    "hostname": (getattr(guest, "hostName", "") or values.get("name") or "")[:190],
                    "operating_system": (
                        getattr(guest, "guestFullName", "") or values.get("config.guestFullName") or ""
                    )[:190],
                    "power_state": str(values.get("runtime.powerState") or "unknown"),
                    "network": network[:190],
                    "portgroup_key": group_key,
                    "dvswitch_name": networks["switches"].get(switch_uuid, ""),
                    "vswitch_name": host.get("portgroups", {}).get(network, "") if not switch_uuid else "",
                    "vm_host_name": host.get("name", ""),
                    "vm_id": vm_id,
                    "nic_key": str(key),
                    "dvport": getattr(dvport, "portKey", "") or "",
                    "dvswitch": switch_uuid,
                    "vm_host": host_id,
                }
            )
    return result


def host_batches(hosts, reader, deadline):
    """Cancel queued hints at the overall deadline; only four socket reads remain."""
    pool = ThreadPoolExecutor(max_workers=4)
    futures = []
    try:
        futures = [pool.submit(reader, host) for host in hosts]
        for future in futures:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NetworkError("vCenter host read timeout")
            try:
                yield future.result(timeout=remaining)
            except TimeoutError:
                raise NetworkError("vCenter host read timeout") from None
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def vcenter_records(config, secret):
    from pyVim.connect import Disconnect
    from pyVmomi import vim, vmodl

    si = connect_vcenter(config, secret)
    view = None
    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder,
            [
                vim.VirtualMachine,
                vim.DistributedVirtualSwitch,
                vim.dvs.DistributedVirtualPortgroup,
                vim.HostSystem,
            ],
            True,
        )
        spec = vmodl.query.PropertyCollector.FilterSpec(
            objectSet=[
                vmodl.query.PropertyCollector.ObjectSpec(
                    obj=view,
                    skip=True,
                    selectSet=[
                        vmodl.query.PropertyCollector.TraversalSpec(
                            name="view", type=vim.view.ContainerView, path="view", skip=False
                        )
                    ],
                )
            ],
            propSet=[
                vmodl.query.PropertyCollector.PropertySpec(
                    type=vim.VirtualMachine,
                    all=False,
                    pathSet=[
                        "name",
                        "guest",
                        "config.guestFullName",
                        "config.hardware.device",
                        "runtime.powerState",
                        "runtime.host",
                    ],
                ),
                vmodl.query.PropertyCollector.PropertySpec(
                    type=vim.DistributedVirtualSwitch, all=False, pathSet=["name", "uuid"]
                ),
                vmodl.query.PropertyCollector.PropertySpec(
                    type=vim.dvs.DistributedVirtualPortgroup,
                    all=False,
                    pathSet=["name", "config.key", "config.distributedVirtualSwitch"],
                ),
                vmodl.query.PropertyCollector.PropertySpec(
                    type=vim.HostSystem,
                    all=False,
                    pathSet=[
                        "name",
                        "config.network.portgroup",
                        "config.network.pnic",
                        "config.network.vnic",
                        "config.network.vswitch",
                        "config.network.proxySwitch",
                        "hardware.systemInfo.uuid",
                        "config.product.fullName",
                        "runtime.powerState",
                        "runtime.connectionState",
                        "configManager.networkSystem",
                    ],
                ),
            ],
        )
        collector = content.propertyCollector
        page = collector.RetrievePropertiesEx(
            specSet=[spec], options=vmodl.query.PropertyCollector.RetrieveOptions(maxObjects=200)
        )
        objects, deadline = [], time.monotonic() + 240
        while page:
            for obj in page.objects:
                if obj.missingSet:
                    raise NetworkError("vCenter property permission missing")
                objects.append((obj.obj, {p.name: p.val for p in obj.propSet}))
                if len(objects) > 100000:
                    if page.token:
                        collector.CancelRetrievePropertiesEx(token=page.token)
                    raise NetworkError("vCenter inventory limit exceeded")
            if not page.token:
                break
            if time.monotonic() > deadline or len(objects) > 100000:
                collector.CancelRetrievePropertiesEx(token=page.token)
                raise NetworkError("vCenter inventory limit exceeded")
            page = collector.ContinueRetrievePropertiesEx(token=page.token)
        # Names may arrive on later pages; resolve backing IDs only after collecting all pages.
        switches = {
            obj._moId: values for obj, values in objects if isinstance(obj, vim.DistributedVirtualSwitch)
        }
        networks = {
            "switches": {v["uuid"]: v["name"] for v in switches.values()},
            "portgroups": {},
            "hosts": {},
        }
        for obj, values in objects:
            if isinstance(obj, vim.dvs.DistributedVirtualPortgroup):
                ds = switches.get(getattr(values.get("config.distributedVirtualSwitch"), "_moId", ""))
                if ds:
                    networks["portgroups"][(ds["uuid"], values.get("config.key") or obj._moId)] = values[
                        "name"
                    ]
            elif isinstance(obj, vim.HostSystem):
                networks["hosts"][obj._moId] = {
                    "name": values.get("name", ""),
                    "portgroups": {
                        pg.spec.name: pg.spec.vswitchName
                        for pg in values.get("config.network.portgroup") or []
                    },
                }
        from . import vmware_hosts

        def host_rows(item):
            obj, values = item
            system = values.get("configManager.networkSystem")
            hints = {}
            if system and values.get("runtime.connectionState", "connected") == "connected":
                try:
                    hints = vmware_hosts.hints(system.QueryNetworkHint())
                except (vmodl.MethodFault, OSError):
                    # Host ownership remains valid; never reuse old physical hints.
                    hints = {}
            return vmware_hosts.records(obj._moId, values, hints)

        hosts = [(obj, values) for obj, values in objects if isinstance(obj, vim.HostSystem)]
        if len(hosts) > 4096:
            raise NetworkError("vCenter host limit exceeded")
        rows = []
        for batch in host_batches(hosts, host_rows, deadline):
            rows.extend(batch)
            if len(rows) > 100000:
                raise NetworkError("vCenter inventory limit exceeded")
        for obj, values in objects:
            if isinstance(obj, vim.VirtualMachine):
                rows.extend(vm_records(obj._moId, values, networks))
                if len(rows) > 100000:
                    raise NetworkError("vCenter inventory limit exceeded")
        return rows
    finally:
        try:
            if view:
                view.Destroy()
        finally:
            Disconnect(si)


async def ping(address):
    """Unprivileged Linux ICMP datagram ping, bounded and cancellation-safe."""
    address = str(ipaddress.ip_address(address))
    proc = await asyncio.create_subprocess_exec(
        "ping",
        "-n",
        "-c",
        "1",
        "-W",
        "1",
        address,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        code = await asyncio.wait_for(proc.wait(), 3)
        if code > 1:
            raise NetworkError("ICMP execution failed")
        return code == 0
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def reverse_dns(address, server):
    import dns.asyncresolver
    import dns.exception
    import dns.reversename

    resolver = dns.asyncresolver.Resolver(configure=server is None)
    resolver.lifetime = 2
    if server:
        resolver.nameservers, resolver.port = [server.address], server.port
    try:
        answer = await resolver.resolve(dns.reversename.from_address(address), "PTR")
        return str(answer[0]).rstrip(".")[:190]
    except dns.exception.DNSException:
        return ""


def windows_dhcp_point(config, secret, address, mac_address):
    """Server-side IP and ClientId filters; scopes are metadata, never all leases."""
    address = str(ipaddress.ip_address(address))
    mac_address = normalized_mac(mac_address)
    if not mac_address:
        raise NetworkError("Gateway MAC required for DHCP lookup")
    if ipaddress.ip_address(address).version != 4:
        return []
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Import-Module DhcpServer -ErrorAction Stop
function Read-Target($action) {
  try { & $action } catch {
    if ($_.FullyQualifiedErrorId -notmatch '20011|20012|20013|20118' -and $_.Exception.Message -notmatch '20011|20012|20013|20118') { throw }
  }
}
$rows = @(
 Read-Target {Get-DhcpServerv4Reservation -IPAddress '__IP__' -ErrorAction Stop} | ForEach-Object {
  [PSCustomObject]@{address=$_.IPAddress.IPAddressToString;mac_address=[string]$_.ClientId;hostname=[string]$_.Name;reserved=$true}
 }
 Read-Target {Get-DhcpServerv4Lease -IPAddress '__IP__' -ErrorAction Stop} | ForEach-Object {
  [PSCustomObject]@{address=$_.IPAddress.IPAddressToString;mac_address=[string]$_.ClientId;hostname=[string]$_.HostName;reserved=$false;lease_state=[string]$_.AddressState}
 }
 Get-DhcpServerv4Scope -ErrorAction Stop | ForEach-Object {
  $scope=$_.ScopeId
  Read-Target {Get-DhcpServerv4Reservation -ScopeId $scope -ClientId '__MAC__' -ErrorAction Stop} | ForEach-Object {
   [PSCustomObject]@{address=$_.IPAddress.IPAddressToString;mac_address=[string]$_.ClientId;hostname=[string]$_.Name;reserved=$true}
  }
  Read-Target {Get-DhcpServerv4Lease -ScopeId $scope -ClientId '__MAC__' -ErrorAction Stop} | ForEach-Object {
   [PSCustomObject]@{address=$_.IPAddress.IPAddressToString;mac_address=[string]$_.ClientId;hostname=[string]$_.HostName;reserved=$false;lease_state=[string]$_.AddressState}
  }
 }
)
ConvertTo-Json -InputObject $rows -Compress -Depth 4
""".replace("__IP__", address).replace("__MAC__", mac_address.replace(":", "-"))
    return windows_dhcp(config, secret, script=script, point=True, preserve_conflicts=True)


def vcenter_point(config, secret, address, mac_address="", hints=()):
    """SearchIndex for the one IP; retrieve only its VM/NIC and backing objects."""
    from pyVim.connect import Disconnect
    from pyVmomi import vim

    si = connect_vcenter(config, secret)
    try:
        content = si.RetrieveContent()
        machines = list(content.searchIndex.FindAllByIp(ip=address, vmSearch=True) or [])
        # Guest tools may omit an IP. A cached MOID is only a lookup hint;
        # current VM/NIC MAC ownership must still match the gateway.
        if not machines:
            machines = [vim.VirtualMachine(id, si._stub) for id in dict.fromkeys(hints)][:4]
        if len(machines) > 4:
            raise NetworkError("Ambiguous VMware IP ownership")
        rows = []
        for vm in machines:
            guest = vm.guest
            config_obj = vm.config
            runtime = vm.runtime
            values = {
                "guest": guest,
                "name": vm.name,
                "config.guestFullName": config_obj.guestFullName,
                "config.hardware.device": config_obj.hardware.device,
                "runtime.powerState": runtime.powerState,
                "runtime.host": runtime.host,
            }
            networks = {"switches": {}, "portgroups": {}, "hosts": {}}
            for nic in config_obj.hardware.device:
                if not isinstance(nic, vim.vm.device.VirtualEthernetCard):
                    continue
                port = getattr(getattr(nic, "backing", None), "port", None)
                uuid = getattr(port, "switchUuid", "")
                if uuid and uuid not in networks["switches"]:
                    ds = content.dvSwitchManager.QueryDvsByUuid(uuid=uuid)
                    networks["switches"][uuid] = ds.name
                group = getattr(port, "portgroupKey", "")
                if group:
                    networks["portgroups"][(uuid, group)] = vim.dvs.DistributedVirtualPortgroup(
                        group, si._stub
                    ).name
            if runtime.host:
                host = runtime.host
                networks["hosts"][host._moId] = {
                    "name": host.name,
                    "portgroups": {
                        pg.spec.name: pg.spec.vswitchName for pg in host.config.network.portgroup or []
                    },
                }
            for record in vm_records(vm._moId, values, networks):
                if record["address"] == address or (mac_address and record["mac_address"] == mac_address):
                    rows.append({**record, "point_match": True})
        if not rows:
            from . import vmware_hosts

            for host in content.searchIndex.FindAllByIp(ip=address, vmSearch=False) or []:
                net = host.config.network
                values = {
                    "name": host.name,
                    "config.network.pnic": net.pnic,
                    "config.network.vnic": net.vnic,
                    "config.network.vswitch": net.vswitch,
                    "config.network.portgroup": net.portgroup,
                    "config.network.proxySwitch": net.proxySwitch,
                    "hardware.systemInfo.uuid": host.hardware.systemInfo.uuid,
                    "config.product.fullName": host.config.product.fullName,
                    "runtime.powerState": host.runtime.powerState,
                    "runtime.connectionState": host.runtime.connectionState,
                }
                hints = vmware_hosts.hints(host.configManager.networkSystem.QueryNetworkHint())
                rows.extend(
                    r for r in vmware_hosts.records(host._moId, values, hints) if r["address"] == address
                )
        return rows
    finally:
        Disconnect(si)
