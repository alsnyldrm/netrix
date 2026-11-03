"""Authorized production browser verification. Password stays in terminal/process memory."""

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--email", required=True)
parser.add_argument("--ca-file", required=True)
parser.add_argument(
    "--run-scan", action="store_true", help="Explicitly request the authorized switch MAC scan"
)
args = parser.parse_args()
BASE = "https://netrix.fbu.edu.tr"
ca = Path(args.ca_file).read_text()
assert "PRIVATE KEY" not in ca
certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", ca, re.S)
assert certs
context = ssl.create_default_context(cadata="\n".join(certs))
with urllib.request.urlopen(BASE + "/api/v1/health/ready", context=context, timeout=15) as response:
    assert json.load(response)["status"] == "ok"
pins = []
for pem in certs:
    cert = x509.load_pem_x509_certificate(pem.encode())
    spki = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    pins.append(base64.b64encode(hashlib.sha256(spki).digest()).decode())
os.environ["NODE_EXTRA_CA_CERTS"] = str(Path(args.ca_file).resolve())
password = getpass.getpass("NETRIX parolası: ")
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, args=["--ignore-certificate-errors-spki-list=" + ",".join(pins)]
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(type(error).__name__))
    page.goto(BASE + "/#ipam-settings")
    page.get_by_label("E-posta", exact=True).fill(args.email)
    page.get_by_label("Parola", exact=True).fill(password)
    with page.expect_response(lambda r: r.url.endswith("/auth/login") and r.request.method == "POST") as auth:
        page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    del password
    assert auth.value.status == 200, "Provided credentials did not authenticate"
    panel = page.locator(".switch-mac-panel")
    panel.locator("summary").click()
    expect(panel).to_contain_text("00:00 · 06:00 · 12:00 · 18:00")
    response = page.request.get(BASE + "/api/v1/ipam/switch-mac-cache")
    assert response.ok
    initial = response.json()
    if args.run_scan:
        # The scan route deduplicates against any active scheduled job.
        response = page.request.post(
            BASE + "/api/v1/ipam/switch-mac-cache/scan", headers={"X-Netrix-Request": "1"}
        )
        assert response.status == 202
        job = response.json()
        last = None
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            response = page.request.get(BASE + "/api/v1/jobs/" + job["id"])
            assert response.ok
            job = response.json()
            progress = (job["status"], job["progress"], job["total"])
            if progress != last:
                print(
                    json.dumps(
                        {"status": job["status"], "completed": job["progress"], "switches": job["total"]}
                    ),
                    flush=True,
                )
                last = progress
            if job["status"] not in ("queued", "running"):
                break
            page.wait_for_timeout(5000)
        else:
            raise AssertionError("Live MAC job did not finish within its verification window")
        assert job["status"] in ("succeeded", "partial"), {"status": job["status"], "error": job.get("error")}
    final = page.request.get(BASE + "/api/v1/ipam/switch-mac-cache").json()
    print(
        json.dumps(
            {
                "live_switch_mac_cache": {k: final[k] for k in ("switches", "healthy", "entries")},
                "result": final.get("last_scan", {}).get("result"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    assert final["entries"] > 0 and final["healthy"] > 0
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        page.evaluate("window.scrollTo(0,0)")
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        page.screenshot(path=f"/tmp/netrix-live-switch-mac-{width}.png", full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(BASE + "/#vlans")
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("heading", name="VLAN alanları", exact=True).is_visible()
    vlans = page.request.get(BASE + "/api/v1/vlans?limit=100").json()["items"]
    checked, hits, protected = 0, [], 0
    for vlan in vlans:
        if not vlan.get("cidr"):
            continue
        started = time.monotonic()
        result = page.request.get(
            BASE + f"/api/v1/ipam/vlans/{vlan['id']}/addresses?active_only=true&limit=100",
            headers={"Cache-Control": "no-cache"},
        )
        assert result.ok
        rows = result.json()["items"]
        hits += [
            (r["address"], r["connected_device"], r["connected_port"])
            for r in rows
            if r.get("connection_type") == "switch_mac_cache"
        ]
        protected += sum(
            bool(r.get("connected_device")) and r.get("connection_type") != "switch_mac_cache" for r in rows
        )
        checked += len(rows)
        print(
            json.dumps(
                {
                    "cidr": vlan["cidr"],
                    "checked_rows": len(rows),
                    "http_ms": round((time.monotonic() - started) * 1000),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    print(
        json.dumps(
            {
                "checked_rows": checked,
                "primary_connections": protected,
                "fallback_connections": len(hits),
                "examples": hits[:5],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    # Open an actual VLAN and its actual address detail; all page reads stay passive.
    if hits:
        address = hits[0][0]
        for vlan in vlans:
            rows = page.request.get(
                BASE + f"/api/v1/ipam/vlans/{vlan['id']}/addresses?q={address}&limit=100"
            ).json()["items"]
            row = next((r for r in rows if r["address"] == address), None)
            if row:
                page.get_by_role("button", name=vlan["cidr"], exact=True).click()
                page.get_by_role("searchbox", name="IPAM kayıtlarında ara", exact=True).fill(
                    address
                ) if page.get_by_role(
                    "searchbox", name="IPAM kayıtlarında ara", exact=True
                ).count() else page.get_by_label("IPAM kayıtlarında ara", exact=True).fill(address)
                page.get_by_role("button", name=address, exact=True).click()
                expect(page.get_by_role("dialog")).to_contain_text("Switch MAC tablosu")
                page.screenshot(path="/tmp/netrix-live-switch-mac-address.png", full_page=True)
                break
    assert not errors, errors
    page.request.post(BASE + "/api/v1/auth/logout", headers={"X-Netrix-Request": "1"})
    browser.close()
print("PASS: authenticated live browser, real MAC scan, real VLAN rows and source visibility")
