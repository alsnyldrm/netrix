"""Fixed backup diagnostics; never expose SSH responses or exception text."""

import asyncssh

from .validation import BackupError


def backup_failure(exc):
    if isinstance(exc, BackupError):
        return exc.code, str(exc)
    if isinstance(exc, TimeoutError):
        return (
            "ssh_timeout",
            "Yedekleme sırasında SSH bağlantısı veya komut yanıtı zaman aşımına uğradı; yedek kaydedilmedi.",
        )
    if isinstance(exc, asyncssh.PermissionDenied):
        return "ssh_authentication_failed", "SSH kullanıcı adı veya parola doğrulanamadı; yedek kaydedilmedi."
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return (
            "ssh_host_key_failed",
            "SSH host anahtarı doğrulanamadı. Cihazın güvenilir host anahtarı kaydını kontrol edin.",
        )
    if isinstance(exc, asyncssh.ProcessError):
        return (
            "ssh_command_failed",
            "SSH yedekleme komutu başarısız oldu. Adaptörü ve hesabın komut okuma yetkisini kontrol edin.",
        )
    if isinstance(exc, (asyncssh.Error, OSError)):
        return (
            "ssh_connection_failed",
            "SSH bağlantısı kurulamadı veya kesildi. Cihazın SSH portunu ve ağ erişimini kontrol edin.",
        )
    return (
        "backup_failed",
        "Yedekleme tamamlanamadı. Cihazın yetkili kapsamını, SSH profilini ve adaptörünü kontrol edin.",
    )
