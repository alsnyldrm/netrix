"""Execute the generated target script with offline PowerShell DHCP command doubles."""

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from netrix.ipam import adapters

MAC = "00:11:22:33:44:55"


@pytest.fixture
def powershell_dhcp(tmp_path, monkeypatch):
    executable = os.environ.get("NETRIX_TEST_PWSH") or shutil.which("pwsh")
    if not executable:
        pytest.skip("Set NETRIX_TEST_PWSH to run offline PowerShell protocol tests")
    module = tmp_path / "DhcpServer"
    module.mkdir()
    (module / "DhcpServer.psm1").write_text(r"""
function Get-DhcpServerv4Scope {
  [CmdletBinding()] param()
  [PSCustomObject]@{ScopeId=[ipaddress]'192.0.2.0'}
  [PSCustomObject]@{ScopeId=[ipaddress]'198.51.100.0'}
}
function Get-DhcpServerv4Reservation {
  [CmdletBinding()] param([ipaddress[]]$IPAddress,[ipaddress]$ScopeId,[string[]]$ClientId)
  $code = 20018
  $category = [System.Management.Automation.ErrorCategory]::ObjectNotFound
  if ($env:NETRIX_DHCP_FIXTURE -eq 'permission') { $code=5; $category=[System.Management.Automation.ErrorCategory]::PermissionDenied }
  if ($env:NETRIX_DHCP_FIXTURE -eq 'database') { $code=20013; $category=[System.Management.Automation.ErrorCategory]::ReadError }
  $errorRecord = [System.Management.Automation.ErrorRecord]::new(
    [System.Exception]::new('Private server message fixture-secret'),
    "DHCP $code",$category,$IPAddress)
  $PSCmdlet.ThrowTerminatingError($errorRecord)
}
function Get-DhcpServerv4Lease {
  [CmdletBinding()] param([ipaddress[]]$IPAddress,[ipaddress]$ScopeId,[string[]]$ClientId)
  if (($IPAddress -and $env:NETRIX_DHCP_FIXTURE -eq 'lease') -or
      ($ClientId -and $ScopeId.IPAddressToString -eq '192.0.2.0' -and $env:NETRIX_DHCP_FIXTURE -eq 'lease')) {
    [PSCustomObject]@{IPAddress=[ipaddress]'192.0.2.10';ClientId='00-11-22-33-44-55';HostName='PC-TARGET';AddressState='Active'}
    return
  }
  $errorRecord = [System.Management.Automation.ErrorRecord]::new(
    [System.Exception]::new('Private server message fixture-secret'),
    'DHCP 20013',[System.Management.Automation.ErrorCategory]::ObjectNotFound,$IPAddress)
  $PSCmdlet.ThrowTerminatingError($errorRecord)
}
Export-ModuleMember -Function Get-DhcpServerv4Scope,Get-DhcpServerv4Reservation,Get-DhcpServerv4Lease
""")
    captured = {}

    def reader(config, secret, **kwargs):
        script = tmp_path / "target.ps1"
        script.write_text(kwargs["script"])
        environment = {
            **os.environ,
            "PSModulePath": str(tmp_path) + os.pathsep + os.environ.get("PSModulePath", ""),
        }
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-File", str(script)],
            env=environment,
            capture_output=True,
            timeout=15,
        )
        captured.update(status=result.returncode, stderr=result.stderr)
        if result.returncode:
            raise adapters.NetworkError("Offline DHCP command failed")
        return adapters.dhcp_records(result.stdout, preserve_conflicts=kwargs["preserve_conflicts"])

    monkeypatch.setattr(adapters, "windows_dhcp", reader)
    return captured


@pytest.mark.parametrize("mode", ["lease", "absent"])
def test_no_reservation_does_not_abort_lease_or_other_scope_queries(powershell_dhcp, monkeypatch, mode):
    monkeypatch.setenv("NETRIX_DHCP_FIXTURE", mode)
    rows = adapters.windows_dhcp_point(None, {}, "192.0.2.10", MAC)
    assert powershell_dhcp["status"] == 0
    assert len(rows) == (1 if mode == "lease" else 0)
    if rows:
        assert rows[0]["hostname"] == "PC-TARGET" and rows[0]["mac_address"] == MAC


@pytest.mark.parametrize("mode", ["permission", "database"])
def test_real_dhcp_source_failures_are_not_treated_as_absence(powershell_dhcp, monkeypatch, mode):
    monkeypatch.setenv("NETRIX_DHCP_FIXTURE", mode)
    with pytest.raises(adapters.NetworkError):
        adapters.windows_dhcp_point(None, {}, "192.0.2.10", MAC)
    assert powershell_dhcp["status"] != 0


@pytest.mark.parametrize(
    "error,expected",
    [
        (b"WIN32 5,Get-DhcpServerv4Lease private fixture-secret", "dhcp_permission_denied"),
        (b"<S>DHCP_x0020_20013,Get-DhcpServerv4Reservation fixture-secret</S>", "dhcp_database_error"),
        (b"DHCP 20123,Get-DhcpServerv4Scope fixture-secret", "dhcp_service_unavailable"),
        (b"Modules_ModuleNotFound private fixture-secret", "dhcp_module_missing"),
        (b"unrecognized private fixture-secret", "dhcp_read_failed"),
    ],
)
def test_winrm_error_details_are_safe_and_cleanup_is_preserved(monkeypatch, error, expected):
    import winrm
    from netrix.ipam.dhcp_errors import DHCPReadError

    cleaned = []

    class Protocol:
        def open_shell(self):
            return "shell"

        def run_command(self, *_):
            return "command"

        def get_command_output_raw(self, *_):
            return b"", error, 1, True

        def cleanup_command(self, *_):
            cleaned.append("command")

        def close_shell(self, *_):
            cleaned.append("shell")

    monkeypatch.setattr(winrm, "Session", lambda *a, **kw: SimpleNamespace(protocol=Protocol()))
    with pytest.raises(DHCPReadError) as caught:
        adapters.windows_dhcp(
            SimpleNamespace(host="dhcp.example.test", port=5986, verify_tls=True),
            {"username": "fixture-user", "password": "fixture-secret"},
            point=True,
        )
    assert caught.value.public_code == expected
    assert "fixture-secret" not in str(caught.value)
    assert "private" not in caught.value.public_message
    assert cleaned == ["command", "shell"]


async def test_typed_dhcp_error_is_reported_without_losing_other_fields():
    from netrix.ipam import pipeline
    from netrix.ipam.dhcp_errors import DHCPReadError

    class Sources:
        async def gateway(self, address):
            return {"mac_address": MAC, "gateway_evidence": []}

        async def vmware(self, address, mac):
            return []

        async def physical(self, address, mac):
            return {"connections": [{"device_id": "switch", "device_name": "Access", "port": "7"}]}

        async def dhcp(self, address, mac):
            raise DHCPReadError("permission_denied", 5)

        async def dns(self, address):
            return "target.example.test"

    result = await pipeline.resolve("192.0.2.10", Sources())
    assert result["status"] == "problem"
    assert result["values"]["hostname"] == "target.example.test"
    assert result["values"]["mac_address"] == MAC
    assert result["values"]["connected_port"] == "7"
    assert result["issues"][0]["code"] == "dhcp_permission_denied"
    assert "yetki" in result["issues"][0]["message"] and "5" in result["issues"][0]["message"]
