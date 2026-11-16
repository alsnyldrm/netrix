"""NETRIX-initiated Entra SAML using a pinned signing certificate and stable identity."""

import json
import logging
import re
import secrets
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML
from pydantic import Field, field_validator, model_validator
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .. import models as m
from ..core import db_session, now, redis_client, settings
from ..schemas import Input
from . import saml_metadata
from .security import DUMMY_HASH, audit, issue_session, set_session_cookie, super_admin, token_hash

PREFIX = "/api/v1/auth/saml"
ACS = PREFIX + "/acs"
COOKIE = "netrix_saml_state"
TTL = 600
MAX_BODY = 256 * 1024
EMAIL = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
DISPLAY = "http://schemas.microsoft.com/identity/claims/displayname"
OBJECT_ID = "http://schemas.microsoft.com/identity/claims/objectidentifier"
USER_NAME = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
ROLE_CLAIMS = (
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
    "roles",
    "groups",
)
ROLES = ("viewer", "operator", "admin")
router = APIRouter(tags=["SAML / Microsoft Entra ID"])


LOG = logging.getLogger("netrix.saml")


class IdentityRejected(Exception):
    def __init__(self, reason):
        self.reason = reason


def rejected(reason, status="invalid"):
    # Fixed internal reasons only; the response and logs never include a claim,
    # assertion identifier, credentials or a raw toolkit exception.
    LOG.warning("SAML sign-in rejected: %s", reason)
    return finish(status)


def public_url(path):
    return settings().public_url.rstrip("/") + path


def https_url(value):
    if not value:
        return value
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.fragment
        or re.search(r"[\s\\]", value)
        or url.port == 0
    ):
        raise ValueError("Geçerli bir HTTPS adresi girin.")
    return value


class SamlInput(Input):
    enabled: bool = False
    sp_entity_id: str = Field(default="", max_length=512)
    idp_metadata_url: str = Field(default="", max_length=1024)
    idp_entity_id: str = Field(default="", max_length=512)
    sso_url: str = Field(default="", max_length=1024)
    slo_url: str = Field(default="", max_length=1024)
    x509_certificate: str = Field(default="", max_length=saml_metadata.MAX_CERT_TEXT)
    email_attribute: str = Field(default=EMAIL, min_length=1, max_length=400)
    display_name_attribute: str = Field(default=DISPLAY, min_length=1, max_length=400)
    nameid_mapping: str = Field(default=C.NAMEID_EMAIL_ADDRESS, max_length=400, pattern=r"^urn:[^\s<>&'\"]+$")
    role_mapping: dict[str, Literal["viewer", "operator", "admin"]] = Field(
        default_factory=dict, max_length=100
    )

    @field_validator("idp_metadata_url")
    @classmethod
    def entra_metadata_url(cls, value):
        return saml_metadata.metadata_url(value)

    @field_validator("sso_url", "slo_url")
    @classmethod
    def endpoint(cls, value):
        return https_url(value)

    @field_validator("sp_entity_id", "idp_entity_id")
    @classmethod
    def entity(cls, value):
        if value.startswith("urn:") and re.fullmatch(r"urn:[^\s<>&'\"]+", value):
            return value
        if any(ch in value for ch in "<>&\"'"):
            raise ValueError("Entity ID alanında geçerli bir URI kullanın.")
        return https_url(value)

    @field_validator("role_mapping")
    @classmethod
    def normalize_roles(cls, value):
        normalized = {key.strip().casefold(): role for key, role in value.items()}
        if len(value) != len(normalized) or any(not key or len(key) > 190 for key in normalized):
            raise ValueError("Rol eşlemeleri benzersiz, 1–190 karakterlik değerler olmalıdır.")
        return normalized

    @model_validator(mode="after")
    def valid_config(self):
        certs = saml_metadata.certificates(self.x509_certificate)
        if self.enabled:
            if not (self.idp_entity_id and self.sso_url and certs):
                raise ValueError("SAML girişi için IdP Entity ID, SSO URL ve imzalama sertifikası gerekli.")
            if not settings().secure_cookies or urlsplit(public_url(ACS)).scheme != "https":
                raise ValueError("SAML girişi için HTTPS ve güvenli oturum çerezleri gerekli.")
            if not saml_metadata.valid_certificates(certs):
                raise ValueError("İmzalama sertifikasının geçerlilik tarihlerini kontrol edin.")
        self.x509_certificate = "\n".join(saml_metadata.pem(cert) for cert in certs)
        return self


def stored(db, *, lock=False):
    if not lock:
        return db.get(m.SamlSettings, 1)
    return db.scalar(select(m.SamlSettings).with_for_update().execution_options(populate_existing=True))


def enabled(db):
    row = stored(db)
    return bool(row and row.config.get("enabled"))


def settings_view(config):
    return {
        **config.model_dump(),
        "sp_entity_id": config.sp_entity_id or public_url(PREFIX + "/metadata"),
        "sp_metadata_url": public_url(PREFIX + "/metadata"),
        "sp_acs_url": public_url(ACS),
        "sp_login_url": public_url(PREFIX + "/login"),
    }


def toolkit_settings(config, *, sp_only=False):
    view = settings_view(config)
    result = {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": view["sp_entity_id"],
            "assertionConsumerService": {"url": view["sp_acs_url"], "binding": C.BINDING_HTTP_POST},
            "NameIDFormat": config.nameid_mapping,
        },
        "security": {
            "wantAssertionsSigned": True,
            "wantNameId": True,
            "requestedAuthnContext": False,
            "rejectDeprecatedAlgorithm": True,
        },
    }
    if config.idp_entity_id and not sp_only:
        result["idp"] = {
            "entityId": config.idp_entity_id,
            "singleSignOnService": {"url": config.sso_url, "binding": C.BINDING_HTTP_REDIRECT},
            "x509certMulti": {
                "signing": [
                    saml_metadata.pem(cert)
                    for cert in saml_metadata.valid_certificates(
                        saml_metadata.certificates(config.x509_certificate)
                    )
                ]
            },
        }
        if config.slo_url:
            result["idp"]["singleLogoutService"] = {"url": config.slo_url, "binding": C.BINDING_HTTP_REDIRECT}
    return result


def request_data(path, post=None):
    # Never construct an SP URL or a return URL from request headers.
    origin = urlsplit(public_url(path))
    return {
        "https": "on",
        "http_host": origin.netloc,
        "script_name": origin.path,
        "get_data": {},
        "post_data": post or {},
    }


def config_hash(config):
    # The URL is only an import shortcut; changing it does not alter trust.
    return token_hash(
        json.dumps(
            {k: v for k, v in settings_view(config).items() if k != "idp_metadata_url"}, sort_keys=True
        )
    )


def rate_limit(client, request):
    ip = request.client.host if request.client else "unknown"
    minute = int(now().timestamp()) // 60
    key = f"netrix:saml:rate:{request.url.path.rsplit('/', 1)[-1]}:{minute}:{token_hash(ip)}"
    count = client.incr(key)
    if count == 1:
        client.expire(key, 120)
    if count > 30:
        raise HTTPException(429, "Çok fazla SAML isteği. Bir dakika sonra tekrar deneyin.")


def state_key(state):
    return "netrix:saml:state:" + token_hash(state)


def finish(status=""):
    response = RedirectResponse("/" + ("?saml=" + status if status else ""), status_code=303)
    response.delete_cookie(COOKIE, path=ACS, secure=True, httponly=True, samesite="none")
    return response


@router.get("/saml/settings")
def get_settings(user=Depends(super_admin), db=Depends(db_session)):
    row = stored(db)
    # Always return an expired config to admins so they can rotate or disable it.
    config = SamlInput.model_construct(**row.config) if row else SamlInput()
    return settings_view(config)


@router.put("/saml/settings")
def save_settings(config: SamlInput, user=Depends(super_admin), db=Depends(db_session)):
    if config.enabled:
        try:
            OneLogin_Saml2_Settings(toolkit_settings(config))
        except Exception:
            raise HTTPException(
                422, "SAML ayarlarını kontrol edin. Kimlik sağlayıcı yapılandırması geçersiz."
            ) from None
    if not config.sp_entity_id:
        config.sp_entity_id = public_url(PREFIX + "/metadata")
    data = config.model_dump()
    row = stored(db, lock=True)
    previous = SamlInput.model_construct(**row.config) if row else None
    if previous is None or previous.model_dump() != data:
        if row:
            row.config = data
        else:
            db.add(m.SamlSettings(id=1, config=data))
        if previous is None or config_hash(previous) != config_hash(config):
            db.execute(
                delete(m.AuthSession).where(
                    m.AuthSession.user_id.in_(select(m.User.id).where(m.User.auth_source == "saml"))
                )
            )
        audit(db, user, "saml_settings", "saml_settings", None, "SAML ayarları güncellendi")
        db.commit()
    return settings_view(config)


class MetadataImport(Input):
    url: str = Field(min_length=1, max_length=1024)

    @field_validator("url")
    @classmethod
    def entra_url(cls, value):
        return saml_metadata.metadata_url(value)


@router.post("/saml/metadata/import")
async def preview_metadata(payload: MetadataImport, request: Request, user=Depends(super_admin)):
    try:
        await run_in_threadpool(rate_limit, redis_client(), request)
        document = await saml_metadata.download(payload.url)
        return await run_in_threadpool(saml_metadata.parse, document, payload.url)
    except RedisError:
        raise HTTPException(503, "Metadata aktarımı şu anda kullanılamıyor.") from None
    except saml_metadata.MetadataUnavailable as exc:
        raise HTTPException(502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/auth/saml/metadata")
def metadata(db=Depends(db_session), download: bool = False):
    row = stored(db)
    config = SamlInput.model_construct(**row.config) if row else SamlInput()
    # Metadata is available before configuring or enabling the provider.
    toolkit = OneLogin_Saml2_Settings(toolkit_settings(config, sp_only=True), sp_validation_only=True)
    document = toolkit.get_sp_metadata()
    if toolkit.validate_metadata(document):
        raise HTTPException(503, "NETRIX SAML metadata oluşturulamadı.")
    if download:
        return Response(
            document,
            media_type="application/xml",
            headers={
                "Content-Disposition": 'attachment; filename="netrix-saml-metadata.xml"',
            },
        )
    return Response(document, media_type="application/samlmetadata+xml")


@router.get("/auth/saml/login")
def login(request: Request, db=Depends(db_session)):
    row = stored(db)
    if not row or not row.config.get("enabled"):
        return finish("disabled")
    try:
        config = SamlInput.model_validate(row.config)
        client = redis_client()
        rate_limit(client, request)
        state = secrets.token_urlsafe(32)
        auth = OneLogin_Saml2_Auth(request_data(PREFIX + "/login"), toolkit_settings(config))
        redirect = auth.login(return_to=state)
        client.set(state_key(state), json.dumps([auth.get_last_request_id(), config_hash(config)]), ex=TTL)
    except HTTPException:
        raise
    except Exception:
        return finish("unavailable")
    response = RedirectResponse(redirect, status_code=303)
    response.set_cookie(COOKIE, state, max_age=TTL, secure=True, httponly=True, samesite="none", path=ACS)
    return response


async def extract_form(request):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/x-www-form-urlencoded"
    ):
        return None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            return None
        body.extend(chunk)
    try:
        form = parse_qs(body.decode("ascii"), max_num_fields=6, strict_parsing=True, errors="strict")
    except (ValueError, UnicodeError):
        return None
    if any(len(form.get(key, ())) != 1 for key in ("SAMLResponse", "RelayState")):
        return None
    return {key: form[key][0] for key in ("SAMLResponse", "RelayState")}


def validate_response(config, form, request_id):
    auth = OneLogin_Saml2_Auth(request_data(ACS, form), toolkit_settings(config))
    auth.process_response(request_id=request_id)
    if (
        auth.get_errors()
        or not auth.is_authenticated()
        or auth.get_last_response_in_response_to() != request_id
    ):
        raise ValueError()
    # Entra emits a single bearer confirmation for the initiating request.
    # Require the exact recipient and request ID on the signed assertion.
    root = OneLogin_Saml2_XML.to_etree(auth.get_last_response_xml())
    ns = C.NSMAP
    assertion = root.find("saml:Assertion", ns)
    sp = settings_view(config)
    if assertion is None or root.get("Destination") != sp["sp_acs_url"]:
        raise ValueError()
    confirmations = assertion.findall("saml:Subject/saml:SubjectConfirmation", ns)
    restrictions = assertion.findall("saml:Conditions/saml:AudienceRestriction", ns)
    if (
        len(confirmations) != 1
        or confirmations[0].get("Method") != C.CM_BEARER
        or not restrictions
        or any(
            sp["sp_entity_id"] not in {a.text for a in restriction.findall("saml:Audience", ns)}
            for restriction in restrictions
        )
    ):
        raise ValueError()
    confirmation = confirmations[0].find("saml:SubjectConfirmationData", ns)
    expires = auth.get_last_assertion_not_on_or_after()
    assertion_id = auth.get_last_assertion_id()
    if (
        confirmation is None
        or confirmation.get("Recipient") != sp["sp_acs_url"]
        or confirmation.get("InResponseTo") != request_id
        or not assertion_id
        or not expires
        or not 0 < expires - now().timestamp() < 86400
    ):
        raise ValueError()
    return auth, assertion_id, expires


def identity(auth, config):
    attrs = auth.get_attributes()

    def claim(key):
        values = attrs.get(key, [])
        return values[0].strip() if len(values) == 1 else ""

    name_id = (auth.get_nameid() or "").strip()
    candidates = [claim(config.email_attribute), name_id, claim(USER_NAME)]
    email = next(
        (
            value.casefold()
            for value in candidates
            if len(value.casefold()) <= 190 and re.fullmatch(r"[^\s@\x00-\x1f]+@[^\s@\x00-\x1f]+", value)
        ),
        "",
    )
    if not email:
        raise IdentityRejected("missing_email")
    object_id = claim(OBJECT_ID)
    if object_id:
        try:
            subject = "oid:" + str(UUID(object_id))
        except ValueError:
            raise IdentityRejected("missing_subject") from None
    elif auth.get_nameid_format() == C.NAMEID_PERSISTENT and 0 < len(name_id) <= 390:
        subject = "persistent:" + name_id
    else:
        raise IdentityRejected("missing_subject")
    values = {value.strip().casefold() for key in ROLE_CLAIMS for value in attrs.get(key, [])}
    matched = {config.role_mapping[value] for value in values if value in config.role_mapping}
    role = next((role for role in ROLES if role in matched), "viewer")
    return subject, email, (claim(config.display_name_attribute) or email)[:120], role


def provision(db, config, auth):
    subject, email, display, role = identity(auth, config)
    link = db.scalar(
        select(m.SamlIdentity).where(
            m.SamlIdentity.issuer == config.idp_entity_id, m.SamlIdentity.subject == subject
        )
    )
    conflict = db.scalar(
        select(m.User.id).where(
            m.User.auth_source == "saml",
            m.User.email == email,
            *((m.User.id != link.user_id,) if link else ()),
        )
    )
    if conflict:
        raise IdentityRejected("account_conflict")
    if link:
        user = db.scalar(select(m.User).where(m.User.id == link.user_id).with_for_update())
        db.refresh(link)
        if not user or user.auth_source != "saml":
            raise IdentityRejected("account_conflict")
        if not user.is_active:
            raise IdentityRejected("account_inactive")
        user.email, user.display_name = email, display
        if not link.manual_role and user.role != role:
            user.role = role
            db.execute(delete(m.AuthSession).where(m.AuthSession.user_id == user.id))
        return user
    user = m.User(email=email, display_name=display, password_hash=DUMMY_HASH, auth_source="saml", role=role)
    db.add(user)
    db.flush()
    db.add(m.SamlIdentity(user_id=user.id, issuer=config.idp_entity_id, subject=subject))
    return user


def complete(request, db, form):
    state = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", state) or not secrets.compare_digest(
        state.encode(), form["RelayState"].encode()
    ):
        return finish("expired")
    try:
        client = redis_client()
        rate_limit(client, request)
        stored_state = client.getdel(state_key(state))
        if not stored_state:
            return finish("expired")
        request_id, digest = json.loads(stored_state)
        row = stored(db)
        if not row or not row.config.get("enabled"):
            return finish("disabled")
        snapshot = row.config
        config = SamlInput.model_validate(snapshot)
        if not request_id or config_hash(config) != digest:
            return finish("expired")
        auth, assertion_id, expires = validate_response(config, form, request_id)
        # The assertion and the initiating browser's request are each one-use,
        # even if two API processes receive the same request concurrently.
        replay = "netrix:saml:assertion:" + token_hash(config.idp_entity_id + "\n" + assertion_id)
        if not client.set(replay, 1, nx=True, ex=int(expires - now().timestamp()) + 61):
            return rejected("replayed_assertion")
        row = stored(db, lock=True)
        if not row or row.config != snapshot:
            return finish("expired")
        user = provision(db, config, auth)
        token = issue_session(db, user)
        audit(db, user, "saml_login", "users", user.id, "Microsoft Entra ID ile oturum açıldı")
        db.commit()
    except IdentityRejected as exc:
        return rejected(exc.reason, exc.reason)
    except RedisError:
        return rejected("redis_unavailable", "unavailable")
    except IntegrityError:
        return rejected("account_integrity", "account_conflict")
    except (ValueError, TypeError):
        return rejected("response_validation")
    except HTTPException:
        raise
    except Exception:
        # Neither raw toolkit errors nor assertion/claim contents are public.
        return rejected("unexpected_failure", "unavailable")
    response = finish()
    set_session_cookie(response, token)
    return response


@router.post("/auth/saml/acs")
async def acs(request: Request, db=Depends(db_session)):
    form = await extract_form(request)
    if form is None:
        return rejected("invalid_form")
    return await run_in_threadpool(complete, request, db, form)
