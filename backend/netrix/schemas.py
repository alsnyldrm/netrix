import ipaddress
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JobInput(Input):
    kind: Literal[
        "discovery", "backup", "monitor", "identify", "test_snmp", "test_snmpv2c", "test_ssh", "test_api"
    ]
    target_id: str = Field(min_length=1, max_length=36)


class ConnectionTestInput(Input):
    protocol: Literal["snmpv3", "snmpv2c", "ssh", "rest"]


class SiteInput(Input):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = Field(default="", max_length=400)
    timezone: str = "Europe/Istanbul"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("Geçersiz saat dilimi") from exc
        return value


class VRFInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)


class VLANInput(Input):
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(default="default", min_length=1, max_length=80)
    vid: int = Field(ge=1, le=4094)


class DeviceTypeInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)


class DeviceInput(Input):
    name: str = Field(min_length=1, max_length=120)
    management_ip: str
    vrf_id: str
    site_id: str | None = None
    vendor: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=100)
    kind: str = Field(default="other", min_length=1, max_length=20)
    lifecycle_status: Literal["planned", "active", "maintenance", "retired"] = "active"
    adapter: Literal[
        "ios",
        "junos",
        "fortios",
        "linux",
        "rest",
        "aruba_5400",
        "aruba_2900",
        "aruba_6100",
        "aruba_7200",
        "hp_1950",
    ] = "ios"
    snmp_credential_id: str | None = None
    config_credential_id: str | None = None
    snmp_port: int = Field(default=161, ge=1, le=65535)
    config_port: int = Field(default=22, ge=1, le=65535)
    ssh_trust_host_key: bool = False
    config_path: str = Field(default="/api/config", max_length=200, pattern=r"^/[A-Za-z0-9/_?=.&%-]*$")
    identity_path: str = Field(default="/api/system", max_length=200, pattern=r"^/[A-Za-z0-9/_?=.&%-]*$")
    monitoring_enabled: bool = False
    monitor_interval: int = Field(default=300, ge=60, le=86400)
    backup_interval: int = Field(default=0, ge=0, le=2592000)
    backup_group_id: str | None = None
    backup_retention: int = Field(default=0, ge=0, le=10000)

    @field_validator("management_ip")
    @classmethod
    def ip(cls, v):
        value = ipaddress.ip_address(v)
        if value.is_multicast or value.is_unspecified or value.is_loopback or value.is_link_local:
            raise ValueError("Yönetilebilir bir unicast IP adresi gerekli")
        return str(value)

    @model_validator(mode="after")
    def intervals(self):
        if 0 < self.backup_interval < 300:
            raise ValueError("Yedekleme aralığı en az 300 saniye olmalı")
        return self


class PrefixInput(Input):
    cidr: str
    vrf_id: str
    site_id: str | None = None
    vlan_id: str | None = None
    description: str = Field(default="", max_length=400)

    @field_validator("cidr")
    @classmethod
    def network(cls, value):
        return str(ipaddress.ip_network(value, strict=True))


class IPInput(Input):
    address: str
    vrf_id: str
    prefix_id: str
    interface_id: str | None = None
    hostname: str = Field(default="", max_length=190)
    status: Literal["reserved", "active", "deprecated"] = "reserved"

    @field_validator("address")
    @classmethod
    def ip(cls, value):
        return str(ipaddress.ip_address(value))


class ScopeInput(Input):
    name: str = Field(min_length=1, max_length=120)
    cidr: str
    vrf_id: str
    credential_id: str
    site_id: str | None = None
    exclusions: list[str] = Field(default_factory=list, max_length=256)
    seeds: list[str] = Field(default_factory=list, max_length=1024)
    enabled: bool = True
    interval_seconds: int = Field(default=0, ge=0, le=2592000)

    @model_validator(mode="after")
    def scope(self):
        network = ipaddress.ip_network(self.cidr, strict=True)
        self.cidr = str(network)
        if (
            network.is_multicast
            or network.is_loopback
            or network.is_link_local
            or network.is_unspecified
            or network.prefixlen == 0
        ):
            raise ValueError("Sınırlandırılmış unicast kapsam gerekli")
        self.exclusions = [str(ipaddress.ip_network(v, strict=False)) for v in self.exclusions]
        if any(
            ipaddress.ip_network(v).version != network.version
            or not ipaddress.ip_network(v).subnet_of(network)
            for v in self.exclusions
        ):
            raise ValueError("Hariç tutulan ağlar kapsamın içinde olmalı")
        self.seeds = list(dict.fromkeys(str(ipaddress.ip_address(v)) for v in self.seeds))
        if any(ipaddress.ip_address(v) not in network for v in self.seeds):
            raise ValueError("Hedef adres kapsam dışında")
        if (network.version == 6 or network.num_addresses > 1024) and not self.seeds:
            raise ValueError("IPv6 ve 1024 adresten büyük ağlar için açık hedef listesi gerekli")
        if 0 < self.interval_seconds < 300:
            raise ValueError("Zamanlama en az 300 saniye olmalı")
        return self


class SecretInput(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=2000)
    cli_password: str = Field(default="", max_length=2000)
    auth_key: str = Field(default="", max_length=200)
    priv_key: str = Field(default="", max_length=200)
    auth_protocol: Literal["sha256", "sha1"] = "sha256"
    community: str = Field(default="", max_length=255)
    token: str = Field(default="", max_length=2000)

    @field_validator("cli_password")
    @classmethod
    def terminal_secret(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Genişletilmiş CLI parolası kontrol karakteri içeremez")
        return value


class CredentialInput(Input):
    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["snmpv3", "snmpv2c", "ssh", "rest"]
    secret: SecretInput

    @model_validator(mode="after")
    def valid(self):
        if self.protocol != "ssh" and self.secret.cli_password:
            raise ValueError("Genişletilmiş CLI parolası yalnızca SSH profili içindir")
        if self.protocol == "snmpv3" and (
            not self.secret.username or len(self.secret.auth_key) < 8 or len(self.secret.priv_key) < 8
        ):
            raise ValueError(
                "SNMPv3 authPriv için kullanıcı, en az 8 karakter auth ve AES privacy anahtarı gerekli"
            )
        if self.protocol == "snmpv2c" and not self.secret.community.strip():
            raise ValueError("SNMPv2c community gerekli")
        if self.protocol == "ssh" and (not self.secret.username or not self.secret.password):
            raise ValueError("SSH kullanıcı ve parola gerekli")
        if self.protocol == "rest" and not self.secret.token:
            raise ValueError("API token gerekli")
        return self


class RuleInput(Input):
    name: str = Field(min_length=1, max_length=120)
    metric: Literal["availability", "utilization", "config_change", "no_data"]
    threshold: float = Field(default=80, ge=0, le=10000000)
    recovery_threshold: float = Field(default=70, ge=0)
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    severity: Literal["info", "warning", "critical"] = "warning"
    enabled: bool = True

    @model_validator(mode="after")
    def rule(self):
        if self.metric == "utilization" and (
            self.threshold > 100 or self.recovery_threshold > self.threshold
        ):
            raise ValueError("Kullanım eşiği 0–100, iyileşme eşiği alarm eşiğinden küçük/eşit olmalı")
        if self.metric == "no_data" and self.threshold < 60:
            raise ValueError("Veri yok eşiği en az 60 saniye olmalı")
        return self


class UserInput(Input):
    email: str = Field(min_length=3, max_length=190, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=200, json_schema_extra={"format": "password"})
    role: Literal["admin", "operator", "viewer"] = "viewer"

    @field_validator("email")
    @classmethod
    def normalized(cls, value):
        return value.casefold()


class SetupInput(UserInput):
    setup_token: str = Field(min_length=20, max_length=200)


class LoginInput(Input):
    email: str = Field(max_length=190)
    password: str = Field(max_length=200)


class PasswordInput(Input):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class BackupGroupInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    interval_seconds: int = Field(default=0, ge=0, le=2592000)
    retention_count: int = Field(default=0, ge=0, le=10000)

    @field_validator("interval_seconds")
    @classmethod
    def interval(cls, value):
        if 0 < value < 300:
            raise ValueError("Aralık 0 veya en az 300 saniye olmalı")
        return value


class SelectionInput(Input):
    ids: list[str] = Field(max_length=4096)


class InterfaceSelectionInput(Input):
    # The old full selection request remains supported for existing API clients.
    ids: list[str] | None = Field(default=None, max_length=4096)
    include_ids: list[str] = Field(default_factory=list, max_length=4096)
    exclude_ids: list[str] = Field(default_factory=list, max_length=4096)

    @model_validator(mode="after")
    def disjoint_selection(self):
        if self.ids is not None and (self.include_ids or self.exclude_ids):
            raise ValueError("Tam seçim ve değişen seçim birlikte gönderilemez")
        if set(self.include_ids) & set(self.exclude_ids):
            raise ValueError("Bir arayüz aynı anda eklenip kaldırılamaz")
        return self


class BulkInput(Input):
    ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["update", "delete", "disable", "enable", "restore"]
    changes: dict = Field(default_factory=dict)


class InventoryFilter(Input):
    field: str
    op: Literal["contains", "eq", "ne", "gt", "lt"] = "contains"
    value: str = Field(max_length=200)
    join: Literal["and", "or"] = "and"


class DeviceTransferInput(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    content: str = Field(min_length=1, max_length=1398104)
    apply: bool = False
    test_after: bool = False


class DeviceCSVExportInput(Input):
    ids: list[str] = Field(min_length=1, max_length=500)


class ImportTestStatusInput(Input):
    ids: list[str] = Field(min_length=1, max_length=1000)
