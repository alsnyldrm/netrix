from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

DEFAULT_IDLE_TIMEOUT_MINUTES = 15


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TerminalAppearance(Input):
    font: Literal["ubuntu", "plex", "system"] = "ubuntu"
    font_size: int = Field(default=15, ge=10, le=28)
    font_weight: Literal[400, 700] = 400
    background: str = Field(default="#300a24", pattern=r"^#[0-9a-fA-F]{6}$")
    commands_width: int = Field(default=300, ge=240, le=560)
    commands_collapsed: bool = False


class Preferences(Input):
    ui_font: Literal[
        "theme",
        "ibm-plex-sans",
        "inter",
        "source-sans-3",
        "roboto",
        "open-sans",
        "noto-sans",
        "fira-sans",
        "work-sans",
        "public-sans",
        "manrope",
        "dm-sans",
        "plus-jakarta-sans",
        "libre-franklin",
        "nunito-sans",
        "lexend",
    ] = "theme"
    palette: Literal[
        "cobalt", "teal", "violet", "amber", "forest", "slate", "rose", "cyan", "orange", "indigo"
    ] = "cobalt"
    design: Literal["atlas", "orbit", "terminal", "panorama", "focus"] = "atlas"
    timezone: str = "Europe/Istanbul"
    locale: Literal["tr-TR", "en-GB", "en-US", "de-DE"] = "tr-TR"
    hour12: bool = False
    terminal: TerminalAppearance = Field(default_factory=TerminalAppearance)
    features: list[Literal["saved_commands", "session_dock", "compact_tables", "reduced_motion"]] = Field(
        default_factory=lambda: ["saved_commands", "session_dock"], max_length=4
    )

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Geçerli bir IANA saat dilimi seçin") from None
        return value


class SSHProfile(Input):
    name: str = Field(min_length=1, max_length=120)
    group_ids: list[str] = Field(default_factory=list, max_length=10000)
    username: str = Field(min_length=1, max_length=120)
    password: SecretStr | None = Field(default=None, max_length=4096)
    private_key: SecretStr | None = Field(default=None, max_length=16384)
    passphrase: SecretStr | None = Field(default=None, max_length=4096)
    port: int = Field(default=22, ge=1, le=65535)
    initial_command: str = Field(default="", max_length=2000)
    connect_timeout: int = Field(default=10, ge=3, le=30)
    idle_timeout_minutes: int = Field(default=DEFAULT_IDLE_TIMEOUT_MINUTES, ge=1, le=240)


class SavedCommand(Input):
    id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=80)
    command: str = Field(min_length=1, max_length=4000)


class Commands(Input):
    items: list[SavedCommand] = Field(max_length=50)


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    device_ids: list[str] = Field(default_factory=list, max_length=10000)


class SessionInput(Input):
    device_id: str
    cols: int = Field(default=100, ge=20, le=300)
    rows: int = Field(default=30, ge=5, le=100)


class BatchInput(Input):
    device_ids: list[str] = Field(min_length=1, max_length=100)
    command: SecretStr = Field(min_length=1, max_length=4000)
    timeout: int = Field(default=30, ge=5, le=120)


class BatchDraftInput(Input):
    device_ids: list[str] = Field(min_length=1, max_length=100)
    command: SecretStr = Field(default=SecretStr(""), max_length=4000)
    timeout: int = Field(default=30, ge=5, le=120)
