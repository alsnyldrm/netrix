import ipaddress
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..schemas import Input


class DNSInput(Input):
    name: str = Field(min_length=1, max_length=120)
    address: str
    port: int = Field(default=53, ge=1, le=65535)

    @field_validator("address")
    @classmethod
    def address_value(cls, value):
        return str(ipaddress.ip_address(value))


class PrefixSettings(Input):
    scan_authorized: bool | None = None
    dns_server_id: str | None = None
    vlan_device_id: str | None = None
    scope_id: str | None = None
    warning_threshold: int = Field(default=80, ge=1, le=100)
    ping_enabled: bool = False
    ping_interval: int = Field(default=300, ge=30, le=86400)
    discovery_enabled: bool = False
    discovery_interval: int = Field(default=3600, ge=60, le=2592000)


class IntegrationInput(Input):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["vcenter", "windows_dhcp"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=190)
    password: str = Field(default="", max_length=2000)
    enabled: bool = False
    verify_tls: bool = True
    prefix_ids: list[str] = Field(default_factory=list, max_length=256)
    interval_seconds: int = Field(default=0, ge=0, le=2592000)

    @field_validator("host")
    @classmethod
    def hostname(cls, value):
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", value):
                raise ValueError("Yalnızca sunucu adı veya IP girin; URL kullanmayın") from None
            return value.lower()

    @model_validator(mode="after")
    def valid(self):
        if 0 < self.interval_seconds < 60:
            raise ValueError("Eşitleme aralığı en az 60 saniye olmalı")
        if self.enabled and not self.prefix_ids:
            raise ValueError("En az bir yetkili ağ bloğu seçin")
        return self


class LiveInput(Input):
    interface_id: str | None = None
    integration_id: str | None = None


class AddressBulkInput(Input):
    ids: list[str] = Field(min_length=1, max_length=1000)
    action: Literal["update", "delete"]
    changes: dict = Field(default_factory=dict)


class PlacementInput(Input):
    device_id: str
    start_unit: int = Field(ge=1, le=60)
    units: int = Field(ge=1, le=60)


class IPPlacementInput(Input):
    address_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=20)
    vendor: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=100)
    start_unit: int = Field(ge=1, le=60)
    units: int = Field(ge=1, le=60)


class RackAccessoryInput(Input):
    kind: Literal["brush_organizer"] = "brush_organizer"
    start_unit: int = Field(ge=1, le=60)
    units: int = Field(default=1, ge=1, le=60)


class ModelImageInput(Input):
    url: str = Field(max_length=500)
    source: str = Field(max_length=500)

    @field_validator("url", "source")
    @classmethod
    def official_url(cls, value, info):
        from urllib.parse import urlsplit

        from .model_images import IMAGE_HOSTS, SOURCE_HOSTS

        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or url.hostname not in (IMAGE_HOSTS if info.field_name == "url" else SOURCE_HOSTS)
        ):
            raise ValueError(
                "Görsel için HPE, Fortinet veya cdn.blueally.com HTTPS adresi gerekli"
                if info.field_name == "url"
                else "Ürün sayfası için HPE veya Fortinet (docs.fortinet.com dahil) HTTPS adresi gerekli"
            )
        return value


class PrefixSelection(Input):
    ids: list[str] = Field(min_length=1, max_length=100)


class PrefixDeleteInput(PrefixSelection):
    confirmation: str = Field(min_length=64, max_length=64)
