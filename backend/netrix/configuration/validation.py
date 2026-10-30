"""Backup capabilities and safe, fixed error messages (never remote output)."""

import re

SSH_BACKUP_ADAPTERS = frozenset(
    {"ios", "junos", "fortios", "linux", "aruba_5400", "aruba_2900", "aruba_6100", "aruba_7200"}
)
MAX_CONFIG_BYTES = 4 * 1024 * 1024


class BackupError(ValueError):
    MESSAGES = {
        "cli_rejected": "SSH yanıtı konfigürasyon yerine komut hatası içeriyor. Cihaza uygun adaptörü ve SSH hesabının komut yetkisini kontrol edin; yedek kaydedilmedi.",
        "empty_config": "Cihaz boş konfigürasyon döndürdü; yedek kaydedilmedi.",
        "invalid_saved_config": "Bu eski kayıt konfigürasyon yerine SSH komut hatası içeriyor. Cihazın adaptörünü düzeltip yeniden yedek alın.",
        "aruba_privilege": "Aruba hesabı Manager/Enable (#) yetkisinde oturum açmalı. Cihazdaki SSH hesabının okuma yetkisini kontrol edin.",
        "aruba_command": "Aruba komutu reddedildi veya çıktı sayfalandı. Adaptör seçimini ve hesabın komut yetkilerini kontrol edin; yedek kaydedilmedi.",
        "aruba_incomplete": "Aruba yanıtı eksik veya geçerli bir konfigürasyon değil; yedek kaydedilmedi.",
        "ssh_required": "Yedekleme ve karşılaştırma yalnızca SSH ile yapılır. Cihaza SSH profili ve uyumlu adaptör atayın.",
        "scp_failed": "FortiGate SCP yedeği alınamadı. SSH erişimini, admin-scp ayarını ve hesabın SCP yedekleme yetkisini kontrol edin.",
        "too_large": "Konfigürasyon 4 MB sınırını aşıyor; yedek kaydedilmedi.",
        "invalid_fortios": "Geçerli FortiGate sys_config yedeği alınamadı. Eksik, sayfalanmış veya hatalı çıktı yedek olarak kabul edilmez.",
        "connection_changed": "Yedekleme sırasında bağlantı ayarı değişti; sonuç kaydedilmedi.",
        "invalid_baseline": "Seçilen eski kayıt geçerli bir FortiGate sys_config yedeği değil. Önce SSH ile yeni bir yedek alın.",
    }

    def __init__(self, code):
        self.code = code
        super().__init__(self.MESSAGES[code])


def require_ssh_backup(device, profile):
    if device.adapter not in SSH_BACKUP_ADAPTERS or not profile or profile.protocol != "ssh":
        raise BackupError("ssh_required")
    return profile


def validate_cli_output(content):
    """Reject CLI diagnostics even when an SSH server reports exit status zero."""
    if not content.strip():
        raise BackupError("empty_config")
    if len(content.encode()) > MAX_CONFIG_BYTES:
        raise BackupError("too_large")
    if re.search(
        r"(?im)^\s*(?:%\s*)?(?:SSH command execution is not supported\.?|"
        r"invalid (?:input|command)|unknown command|unrecognized command|"
        r"incomplete command|permission denied|access denied|authorization failed|"
        r"not authorized|command not found|command parse error|command fail)\b"
        r"|(?im:^\s*--\s*more\s*--)",
        content,
    ):
        raise BackupError("cli_rejected")


def validate_fortios_backup(content):
    # SCP verifies transport length. These checks reject CLI pages/error text,
    # not certify that every VDOM/certificate is included or a restore will succeed.
    lines = content.splitlines()
    if (
        not lines
        or not re.fullmatch(r"#config-version=\S+", lines[0])
        or not re.search(r"(?m)^config \S", content)
        or content.rstrip().splitlines()[-1] != "end"
        or re.search(r"(?m)^\s*(?:--More--|Command fail|command parse error|Permission denied)", content)
    ):
        raise BackupError("invalid_fortios")
