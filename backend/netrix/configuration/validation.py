"""Backup capabilities and safe, fixed error messages (never remote output)."""

import re

SSH_BACKUP_ADAPTERS = frozenset({"ios", "junos", "fortios", "linux"})
MAX_CONFIG_BYTES = 4 * 1024 * 1024


class BackupError(ValueError):
    MESSAGES = {
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
