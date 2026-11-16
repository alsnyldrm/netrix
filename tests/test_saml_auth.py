"""Isolated SAML IdP signs fixture assertions using ephemeral certificates."""

import base64
import zlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from lxml import etree
from netrix import models as m
from netrix.core import now, settings
from netrix.identity import saml
from onelogin.saml2.utils import OneLogin_Saml2_Utils

BASE = "https://netrix.example.test"
ISSUER = "https://sts.windows.net/test-tenant/"
ENTITY = BASE + saml.PREFIX + "/metadata"
ACS = BASE + saml.ACS
SETTINGS = "/api/v1/saml/settings"
ACCOUNT = "person@example.test"
OBJECT_ID = "6641051c-59cf-4b00-9a30-62f015033e80"
OWNER = "alisan.yildirim@fbu.edu.tr"
NAMESPACES = {"saml": saml.C.NS_SAML, "samlp": saml.C.NS_SAMLP}


class Memory:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, ex, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def getdel(self, key):
        return self.values.pop(key, None)


def new_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Local SAML Fixture")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now() - timedelta(days=1))
        .not_valid_after(now() + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return (
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
        cert.public_bytes(serialization.Encoding.PEM).decode(),
    )


@pytest.fixture
def fixture(env, monkeypatch):
    from netrix.main import app

    monkeypatch.setenv("NETRIX_PUBLIC_URL", BASE)
    monkeypatch.setenv("NETRIX_SECURE_COOKIES", "true")
    settings.cache_clear()
    memory = Memory()
    monkeypatch.setattr(saml, "redis_client", lambda: memory)
    signer = new_cert()
    inputs = {
        "enabled": True,
        "idp_entity_id": ISSUER,
        "sso_url": "https://login.microsoftonline.com/test-tenant/saml2",
        "x509_certificate": signer[1],
        "role_mapping": {"Netrix.Operations": "operator"},
    }
    with TestClient(app, base_url=BASE, headers={"X-Netrix-Request": "1"}) as admin:
        assert (
            admin.post(
                "/api/v1/auth/setup",
                json={
                    "email": OWNER,
                    "display_name": "Owner",
                    "password": "fixture-owner-only-password",
                    "setup_token": settings().setup_token,
                },
            ).status_code
            == 201
        )
        assert (
            admin.post(
                "/api/v1/auth/login",
                json={
                    "email": OWNER,
                    "password": "fixture-owner-only-password",
                },
            ).status_code
            == 200
        )
        with TestClient(app, base_url=BASE) as browser:
            yield admin, browser, signer, inputs, memory
    settings.cache_clear()


def activate(admin, config):
    response = admin.put(SETTINGS, json=config)
    assert response.status_code == 200, response.text


def initiate(browser):
    response = browser.get(saml.PREFIX + "/login", follow_redirects=False)
    url = urlsplit(response.headers["location"])
    assert url.hostname == "login.microsoftonline.com"
    assert "SameSite=none" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]
    params = parse_qs(url.query)
    xml = etree.fromstring(zlib.decompress(base64.b64decode(params["SAMLRequest"][0]), -15))
    assert xml.get("AssertionConsumerServiceURL") == ACS
    assert xml.find("saml:Issuer", NAMESPACES).text == ENTITY
    assert xml.find("samlp:RequestedAuthnContext", NAMESPACES) is None
    return xml.get("ID"), params["RelayState"][0]


def assertion(
    request_id, signer, *, subject=OBJECT_ID, email=ACCOUNT, roles=(), signed=True, assertion_id=None
):
    def ts(seconds):
        return (now() + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

    attrs = {
        saml.EMAIL: [email],
        saml.DISPLAY: ["Örnek Entra Hesabı"],
        saml.OBJECT_ID: [subject] if subject else [],
        saml.ROLE_CLAIMS[0]: roles,
    }
    attrs_xml = "".join(
        f'<saml:Attribute Name="{name}">'
        + "".join(f"<saml:AttributeValue>{v}</saml:AttributeValue>" for v in values)
        + "</saml:Attribute>"
        for name, values in attrs.items()
        if values
    )
    xml = f'''<saml:Assertion xmlns:saml="{saml.C.NS_SAML}" ID="{assertion_id or "_" + uuid4().hex}" IssueInstant="{ts(0)}" Version="2.0">
      <saml:Issuer>{ISSUER}</saml:Issuer>
      <saml:Subject><saml:NameID Format="{saml.C.NAMEID_EMAIL_ADDRESS}">{email}</saml:NameID>
      <saml:SubjectConfirmation Method="{saml.C.CM_BEARER}">
      <saml:SubjectConfirmationData InResponseTo="{request_id}" Recipient="{ACS}" NotOnOrAfter="{ts(300)}"/>
      </saml:SubjectConfirmation></saml:Subject>
      <saml:Conditions NotBefore="{ts(-30)}" NotOnOrAfter="{ts(300)}">
        <saml:AudienceRestriction><saml:Audience>{ENTITY}</saml:Audience></saml:AudienceRestriction>
      </saml:Conditions>
      <saml:AuthnStatement AuthnInstant="{ts(0)}"><saml:AuthnContext>
        <saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:X509</saml:AuthnContextClassRef>
      </saml:AuthnContext></saml:AuthnStatement>
      <saml:AttributeStatement>{attrs_xml}</saml:AttributeStatement>
      </saml:Assertion>'''
    if signed:
        xml = OneLogin_Saml2_Utils.add_sign(xml, signer[0], signer[1]).decode()
        if xml.startswith("<?xml"):
            xml = xml.split("?>", 1)[1]
    return base64.b64encode(
        f'''<samlp:Response xmlns:samlp="{saml.C.NS_SAMLP}" xmlns:saml="{saml.C.NS_SAML}"
        ID="_{uuid4().hex}" Version="2.0" IssueInstant="{ts(0)}" Destination="{ACS}" InResponseTo="{request_id}">
        <saml:Issuer>{ISSUER}</saml:Issuer>
        <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
        {xml}</samlp:Response>'''.encode()
    ).decode()


def submit(browser, state, message):
    return browser.post(
        saml.ACS,
        data={"RelayState": state, "SAMLResponse": message},
        headers={"Origin": "https://login.microsoftonline.com"},
        follow_redirects=False,
    )


def login(browser, signer, **kwargs):
    request_id, state = initiate(browser)
    return submit(browser, state, assertion(request_id, signer, **kwargs))


def test_settings_disabled_metadata_and_management_access(fixture):
    admin, browser, _, config, _ = fixture
    assert browser.get("/api/v1/auth/status").json()["saml_enabled"] is False
    assert browser.get(SETTINGS).status_code == 401
    assert (
        browser.get(saml.PREFIX + "/login", follow_redirects=False).headers["location"] == "/?saml=disabled"
    )
    metadata = browser.get(saml.PREFIX + "/metadata")
    assert metadata.status_code == 200
    assert etree.fromstring(metadata.content).get("entityID") == ENTITY
    assert ACS in metadata.text
    assert admin.put(SETTINGS, json={"enabled": True}).status_code == 422
    assert admin.put(SETTINGS, json={**config, "role_mapping": {"Test": "super_admin"}}).status_code == 422
    assert (
        admin.put(
            SETTINGS, json={**config, "sp_entity_id": "https://example.test/?hello=1&other=2"}
        ).status_code
        == 422
    )
    assert admin.put(SETTINGS, json={**config, "x509_certificate": "bad certificate"}).status_code == 422
    activate(admin, config)
    assert browser.get("/api/v1/auth/status").json()["saml_enabled"] is True
    assert browser.get("/api/v1/users").status_code == 401
    assert browser.post("/api/v1/auth/login", json={}).status_code == 403
    assert (
        browser.post(saml.ACS, content=b"bad", follow_redirects=False).headers["location"] == "/?saml=invalid"
    )


def test_signed_login_provisions_reader_and_blocks_local_password(fixture, env):
    admin, browser, signer, config, _ = fixture
    activate(admin, config)
    success = login(browser, signer)
    assert success.headers["location"] == "/"
    assert "netrix_session=" in success.headers["set-cookie"]
    user = browser.get("/api/v1/auth/me").json()
    assert user["role"] == "viewer" and user["auth_source"] == "saml"
    assert user["email"] == ACCOUNT and user["display_name"] == "Örnek Entra Hesabı"
    assert user["ssh_access"] is False and "password_hash" not in user
    assert browser.get(SETTINGS).status_code == 403
    with env() as db:
        db.get(m.User, user["id"]).password_hash = saml.DUMMY_HASH
        db.commit()
        assert db.get(m.SamlIdentity, user["id"]).issuer == ISSUER
    headers = {"X-Netrix-Request": "1"}
    assert (
        browser.post(
            "/api/v1/auth/password",
            headers=headers,
            json={
                "current_password": "fixture",
                "new_password": "fixture-new-password",
            },
        ).status_code
        == 403
    )
    assert (
        browser.post(
            "/api/v1/auth/login", headers=headers, json={"email": ACCOUNT, "password": "fixture"}
        ).status_code
        == 401
    )
    activate(admin, {**config, "enabled": False})
    assert browser.get("/api/v1/auth/me").status_code == 401
    assert admin.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize(
    "case", ["missing_cookie", "expired", "unsigned", "wrong_certificate", "unmatched_request"]
)
def test_client_requires_valid_signed_request(fixture, case):
    admin, browser, signer, config, memory = fixture
    activate(admin, config)
    request_id, state = initiate(browser)
    if case == "missing_cookie":
        browser.cookies.clear()
    if case == "expired":
        memory.getdel(saml.state_key(state))
    if case == "wrong_certificate":
        signer = new_cert()
    if case == "unmatched_request":
        request_id = "_different"
    response = submit(browser, state, assertion(request_id, signer, signed=case != "unsigned"))
    assert response.headers["location"] == (
        "/?saml=expired" if case in {"missing_cookie", "expired"} else "/?saml=invalid"
    )
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_one_use_and_privileged_or_email_only_accounts_never_link(fixture):
    admin, browser, signer, config, _ = fixture
    activate(admin, config)
    request_id, state = initiate(browser)
    message = assertion(request_id, signer)
    assert submit(browser, state, message).headers["location"] == "/"
    browser.cookies.set(saml.COOKIE, state)
    assert submit(browser, state, message).headers["location"] == "/?saml=expired"
    browser.cookies.clear()
    assert login(browser, signer, email=OWNER).headers["location"] == "/?saml=invalid"
    assert (
        login(browser, signer, subject="", email="other@example.test").headers["location"] == "/?saml=invalid"
    )
    assert login(browser, signer, subject=str(uuid4())).headers["location"] == "/?saml=invalid"
    assert admin.get("/api/v1/auth/me").json()["role"] == "super_admin"


def test_mapped_roles_revoke_and_manual_role_persists(fixture):
    admin, browser, signer, config, _ = fixture
    activate(admin, config)
    assert login(browser, signer, roles=["Netrix.Operations"]).headers["location"] == "/"
    user = browser.get("/api/v1/auth/me").json()
    assert user["role"] == "operator"
    assert login(browser, signer).headers["location"] == "/"
    assert browser.get("/api/v1/auth/me").json()["role"] == "viewer"
    assert (
        admin.put(
            f"/api/v1/users/{user['id']}/roles", json={"role": "admin", "ssh_access": False}
        ).status_code
        == 200
    )
    assert (
        login(browser, signer, roles=["Netrix.Operations"], email="renamed@example.test").headers["location"]
        == "/"
    )
    changed = browser.get("/api/v1/auth/me").json()
    assert (
        changed["id"] == user["id"]
        and changed["role"] == "admin"
        and changed["email"] == "renamed@example.test"
    )
    assert browser.get(SETTINGS).status_code == 403
    assert admin.post(f"/api/v1/users/{user['id']}/toggle").status_code == 200
    assert login(browser, signer, email="renamed@example.test").headers["location"] == "/?saml=invalid"
    assert browser.get("/api/v1/auth/me").status_code == 401
