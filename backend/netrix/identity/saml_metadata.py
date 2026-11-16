"""Fetch tenant-specific Entra metadata and extract only SAML trust settings."""

import asyncio
import base64
import binascii
import re
import ssl
from urllib.parse import urlsplit

import httpx
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C

from ..core import now

HOST = "login.microsoftonline.com"
ENTRA_HOST = (HOST, "login.windows.net")
GUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
TENANT = rf"(?:{GUID}|{LABEL}(?:\.{LABEL})+)"
PATH = "/federationmetadata/2007-06/federationmetadata.xml"
NS = {"md": C.NS_MD, "ds": C.NS_DS}
MAX_XML = 256 * 1024
MAX_CERTIFICATES = 8
MAX_CERT_TEXT = 16000
PEM = r"-----BEGIN CERTIFICATE-----[\sA-Za-z0-9+/=]+-----END CERTIFICATE-----"


class MetadataUnavailable(Exception):
    pass


def metadata_url(value):
    if not value:
        return ""
    # Accept just the documented Microsoft endpoints; recreate the URL from
    # constrained components before making a network request.
    escaped_path = re.escape(PATH)
    pattern = rf"https://(?:login\.microsoftonline\.com|login\.windows\.net)/({TENANT}){escaped_path}(?:\?appid=({GUID}))?"
    match = re.fullmatch(pattern, value, flags=re.IGNORECASE | re.ASCII)
    if not match:
        raise ValueError("Microsoft Entra ID uygulamasındaki App Federation Metadata URL adresini girin.")
    tenant, app = match.groups()
    return f"https://{HOST}/{tenant.lower()}{PATH}" + (f"?appid={app.lower()}" if app else "")


def certificates(value):
    if not value:
        return []
    try:
        if len(value) > MAX_CERT_TEXT:
            raise ValueError()
        if value.startswith("-----BEGIN CERTIFICATE-----"):
            blocks = re.findall(PEM, value)
            if not blocks or "".join("".join(block.split()) for block in blocks) != "".join(value.split()):
                raise ValueError()
            parsed = [x509.load_pem_x509_certificate(block.encode()) for block in blocks]
        else:
            parsed = [x509.load_der_x509_certificate(base64.b64decode("".join(value.split()), validate=True))]
        if len(parsed) > MAX_CERTIFICATES:
            raise ValueError()
        for cert in parsed:
            key = cert.public_key()
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError()
        return list(dict.fromkeys(parsed))
    except (ValueError, UnicodeError, binascii.Error, UnsupportedAlgorithm):
        raise ValueError("Geçerli RSA X.509 imzalama sertifikaları girin (en az 2048 bit).") from None


def pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode().strip()


def valid_certificates(certs):
    instant = now()
    return [cert for cert in certs if cert.not_valid_before_utc <= instant < cert.not_valid_after_utc]


async def download(url):
    try:
        async with asyncio.timeout(8):
            async with (
                httpx.AsyncClient(
                    verify=ssl.create_default_context(),
                    follow_redirects=False,
                    trust_env=False,
                    timeout=5,
                    headers={"Accept": "application/xml, text/xml", "Accept-Encoding": "identity"},
                ) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > MAX_XML:
                        raise ValueError("Microsoft metadata XML dosyası izin verilen boyutu aşıyor.")
                return bytes(body)
    except (httpx.HTTPError, TimeoutError):
        raise MetadataUnavailable(
            "Microsoft metadata adresi okunamadı. URL’yi kontrol edip yeniden deneyin."
        ) from None


def parse(document, url):
    try:
        root = ElementTree.fromstring(document, forbid_dtd=True)
        if root.tag != f"{{{C.NS_MD}}}EntityDescriptor":
            raise ValueError()
        issuer = root.get("entityID", "")
        tenant = re.fullmatch(rf"https://sts\.windows\.net/({GUID})/", issuer, flags=re.IGNORECASE)
        if not tenant:
            raise ValueError()
        requested = urlsplit(url).path.split("/")[1]
        if "." not in requested and requested != tenant[1].lower():
            raise ValueError()
        descriptors = [
            node
            for node in root.findall("md:IDPSSODescriptor", NS)
            if C.NS_SAMLP in node.get("protocolSupportEnumeration", "").split()
        ]
        if len(descriptors) != 1:
            raise ValueError()
        sso = descriptors[0]

        def service(name):
            locations = {
                node.get("Location", "")
                for node in sso.findall(f"md:{name}", NS)
                if node.get("Binding") == C.BINDING_HTTP_REDIRECT
            }
            if not locations:
                return ""
            if len(locations) != 1:
                raise ValueError()
            location = locations.pop()
            match = re.fullmatch(
                rf"https://(?:login\.microsoftonline\.com|login\.windows\.net)/({TENANT})/saml2",
                location,
                flags=re.IGNORECASE | re.ASCII,
            )
            if not match or match[1].lower() not in (requested, tenant[1].lower()):
                raise ValueError()
            return location

        login, logout = service("SingleSignOnService"), service("SingleLogoutService")
        keys = list(
            dict.fromkeys(
                "".join((node.text or "").split())
                for key in sso.findall("md:KeyDescriptor", NS)
                if key.get("use") in (None, "signing")
                for node in key.findall("ds:KeyInfo/ds:X509Data/ds:X509Certificate", NS)
            )
        )
        if not login or not keys or len(keys) > MAX_CERTIFICATES or not all(keys):
            raise ValueError()
        certs = [certificates(key)[0] for key in keys]
        bundle = "\n".join(pem(cert) for cert in certs)
        if len(bundle) > MAX_CERT_TEXT:
            raise ValueError()
    except (ValueError, DefusedXmlException, ElementTree.ParseError):
        raise ValueError(
            "XML, geçerli Microsoft Entra SAML ayarları içermiyor. Uygulamanın metadata URL’sini kontrol edin."
        ) from None
    if not valid_certificates(certs):
        raise ValueError("Microsoft metadata XML dosyasında geçerli bir imzalama sertifikası bulunamadı.")
    return {
        "idp_metadata_url": url,
        "idp_entity_id": issuer,
        "sso_url": login,
        "slo_url": logout,
        "x509_certificate": bundle,
    }
