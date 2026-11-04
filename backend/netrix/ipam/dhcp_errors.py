"""Safe DHCP diagnostics: never retain WinRM/PowerShell messages or credentials."""

import re

from ..discovery.protocols import NetworkError

MESSAGES = {
    "permission_denied": "Windows DHCP kayıtlarını okumak için yetki yetersiz.",
    "database_error": "Windows DHCP veritabanı okuması başarısız; bu yanıt kayıt yok olarak değerlendirilmedi.",
    "service_unavailable": "Windows DHCP servisine erişilemedi veya servis çalışmıyor.",
    "module_missing": "Windows DHCP PowerShell modülü bulunamadı veya yüklenemedi.",
    "timeout": "Windows DHCP hedefli sorgusu zaman aşımına uğradı.",
    "read_failed": "Windows DHCP hedefli komutu başarısız oldu.",
}


class DHCPReadError(NetworkError):
    def __init__(self, code, native_code=None):
        self.public_code = "dhcp_" + (code if code in MESSAGES else "read_failed")
        self.public_message = MESSAGES.get(code, MESSAGES["read_failed"])
        if isinstance(native_code, int) and 0 <= native_code <= 99999:
            self.public_message += f" Windows hata kodu: {native_code}."
        super().__init__(self.public_message)


def command_failure(content):
    # PowerShell may serialize error records as CLIXML with escaped spaces/newlines.
    text = content[:16384].decode("utf-8", errors="replace")
    text = re.sub(r"_x00(?:20|0A|0D)_", " ", text, flags=re.IGNORECASE)
    match = re.search(r"\b(?:DHCP|WIN32)\s+([0-9]{1,5})(?=,|\s|<|$)", text, re.IGNORECASE)
    code = int(match[1]) if match else None
    if code in (5, 20121):
        return DHCPReadError("permission_denied", code)
    if code in (20001, 20013):
        return DHCPReadError("database_error", code)
    if code in (1722, 1753, 20017, 20122, 20123, 20124):
        return DHCPReadError("service_unavailable", code)
    if "Modules_ModuleNotFound" in text or "CouldNotAutoloadMatchingModule" in text:
        return DHCPReadError("module_missing")
    return DHCPReadError("read_failed", code)
