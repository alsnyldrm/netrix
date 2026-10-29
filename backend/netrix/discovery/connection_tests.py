"""Real, read-only protocol probes using the device's saved encrypted profile."""

import asyncio
import json

import asyncssh
import httpx

from .protocols import NetworkError, ssh_known_hosts


async def probe(device, protocol, secret, collector):
    async with asyncio.timeout(30):
        if protocol == "snmpv3":
            await collector.probe(device.management_ip, device.snmp_port, secret)
            return "SNMPv3 authPriv bağlantısı ve sistem OID okuması başarılı."
        if protocol == "ssh":
            async with asyncssh.connect(
                device.management_ip,
                port=device.config_port,
                username=secret["username"],
                password=secret["password"],
                known_hosts=ssh_known_hosts(device),
                client_keys=[],
                connect_timeout=10,
                login_timeout=15,
            ):
                if getattr(device, "ssh_trust_host_key", False):
                    return "SSH bağlantısı ve kullanıcı doğrulaması başarılı. Host anahtarı cihazın Anahtara güven ayarıyla kabul edildi."
                return "SSH bağlantısı, host anahtarı ve kullanıcı doğrulaması başarılı."
        if protocol != "rest":
            raise ValueError("Desteklenmeyen test protokolü")
        host = f"[{device.management_ip}]" if ":" in device.management_ip else device.management_ip
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "GET",
                f"https://{host}:{device.config_port}{device.identity_path}",
                headers={"Authorization": f"Bearer {secret['token']}"},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 256 * 1024:
                        raise NetworkError("API yanıtı boyut sınırını aşıyor")
                if not isinstance(json.loads(body), (dict, list)):
                    raise ValueError("API yanıtı JSON nesnesi veya listesi değil")
                return f"API uç noktası token gönderilen HTTPS isteğine HTTP {response.status_code} ve geçerli JSON yanıtı verdi."


def failure(exc, protocol):
    """Public diagnostics are fixed messages; raw exception/response text never escapes."""
    if isinstance(exc, TimeoutError) or isinstance(exc, httpx.TimeoutException):
        return "timeout", "Bağlantı testi zaman aşımına uğradı. Ağ erişimini ve portu kontrol edin."
    if isinstance(exc, asyncssh.PermissionDenied):
        return "authentication_failed", "SSH kullanıcı adı veya parola doğrulanamadı."
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return (
            "host_key_failed",
            "SSH host anahtarı güvenilir kayıtla doğrulanamadı. Cihazı düzenleyerek Anahtara güven seçeneğini işaretleyin veya güvenilir host anahtarı kaydını güncelleyin.",
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return (
                "authentication_failed",
                f"API erişimi reddedildi (HTTP {status}). Token ve yetkilerini kontrol edin.",
            )
        return (
            "http_error",
            f"API uç noktası başarılı yanıt vermedi (HTTP {status}). API yolunu ve erişim yetkilerini kontrol edin.",
        )
    if isinstance(exc, httpx.ConnectError) and "CERTIFICATE_VERIFY_FAILED" in str(exc):
        return (
            "tls_failed",
            "API TLS sertifikası doğrulanamadı. Sertifika zincirini ve hedef adresi kontrol edin.",
        )
    if protocol == "rest" and isinstance(exc, ValueError):
        return "invalid_response", "API uç noktası geçerli bir JSON yanıtı vermedi. API yolunu kontrol edin."
    if protocol == "snmpv3":
        return (
            "snmp_failed",
            "SNMPv3 testi başarısız. Kullanıcı, auth/privacy anahtarları, port ve ağ erişimini kontrol edin.",
        )
    return "connection_failed", "Bağlantı kurulamadı. Ağ erişimini, portu ve erişim profilini kontrol edin."
