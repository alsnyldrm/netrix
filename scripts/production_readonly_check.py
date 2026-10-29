"""Read-only production smoke test; does not create users or run device jobs."""

import base64
import hashlib
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from playwright.sync_api import expect, sync_playwright

cert = x509.load_pem_x509_certificate(Path(".secrets/public-chain.pem").read_bytes())
pin = base64.b64encode(
    hashlib.sha256(cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).digest()
).decode()
with sync_playwright() as p:
    browser = p.chromium.launch(
        args=[
            "--no-proxy-server",
            "--ignore-certificate-errors-spki-list=" + pin,
        ]
    )
    page = browser.new_page(viewport={"width": 1440, "height": 960}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    response = page.goto("https://netrix.fbu.edu.tr/")
    assert response.status == 200
    page.wait_for_load_state("networkidle")
    expect(page.get_by_label("E-posta", exact=True)).to_be_visible()
    expect(page.get_by_label("Parola", exact=True)).to_be_visible()
    status = page.evaluate("async()=>await (await fetch('/api/v1/health/ready')).json()")
    assert status["status"] == "ok"
    bootstrap = page.evaluate("async()=>await (await fetch('/api/v1/auth/status')).json()")
    assert page.evaluate("async()=> (await fetch('/favicon.svg')).status") == 200
    page.screenshot(path="artifacts/production-initial.png", full_page=True)
    assert not errors, errors
    print(
        json.dumps(
            {
                "production_https": "PASS",
                "certificate": "pinned existing Nginx certificate",
                "DNS": "system resolver",
                "bootstrap_required": bootstrap["setup_required"],
                "health": status,
                "console_errors": errors,
            }
        )
    )
    browser.close()
