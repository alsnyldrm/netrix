"""Local browser fixtures only: no real device connections or production API writes."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8203")
assert BASE.startswith("http://127.0.0.1:"), "Local test server required"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    errors, submissions = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    device = {
        "id": "device-1",
        "name": "Fixture firewall",
        "management_ip": "192.0.2.1",
        "kind": "firewall",
        "vendor": "Fixture vendor",
        "model": "Fixture model",
        "lifecycle_status": "active",
    }
    enabled = {"snmpv3", "ssh"}
    reads = 0
    selected = ""
    cancelling = False

    def api(route):
        global reads, selected
        path = urlparse(route.request.url).path.removeprefix("/api/v1/")
        if path == "auth/me":
            data = {"id": "user-1", "display_name": "Browser tester", "role": "admin"}
        elif path == "dashboard":
            data = {"counts": {}}
        elif path == "devices/device-1/connection-tests":
            if route.request.method == "POST":
                selected = route.request.post_data_json["protocol"]
                assert selected in enabled
                submissions.append(selected)
                reads = 0
                route.fulfill(status=202, json={"id": "job-" + str(len(submissions)), "status": "queued"})
                return
            data = {
                "target": device["management_ip"],
                "can_test": bool(enabled),
                "reason": "",
                "protocols": [
                    {
                        "protocol": protocol,
                        "label": label,
                        "enabled": protocol in enabled,
                        "profile_name": "Fixture " + label,
                        "port": 161 if protocol == "snmpv3" else 22,
                        "path": "/api/system" if protocol == "rest" else None,
                    }
                    for protocol, label in [("snmpv3", "SNMPv3"), ("ssh", "SSH"), ("rest", "API")]
                ],
            }
        elif path.startswith("jobs/job-"):
            reads += 1
            if path.endswith("/cancel"):
                data = {"id": path.split("/")[1], "status": "cancelled", "error": "Test iptal edildi"}
            elif cancelling or reads == 1:
                data = {"id": path.split("/")[1], "status": "running"}
            else:
                success = selected != "ssh"
                data = {
                    "id": path.split("/")[1],
                    "status": "succeeded" if success else "failed",
                    "result": {
                        "success": success,
                        "protocol": selected,
                        "message": "Fixture SNMP response"
                        if success
                        else "Fixture SSH authentication failed",
                        "port": 161 if selected == "snmpv3" else 22,
                        "duration_ms": 24,
                        "checked_at": "2026-10-30T09:30:00+00:00",
                    },
                }
        else:
            rows = [device] if path in ("devices", "inventory/devices") else []
            data = {"items": rows, "total": len(rows), "columns": [{"key": k, "label": k} for k in device]}
        route.fulfill(json=data)

    page.route("**/api/v1/**", api)
    page.goto(BASE + "/#devices")
    page.wait_for_load_state("networkidle")
    trigger = page.get_by_role("button", name="Fixture firewall bağlantı testi", exact=True)
    trigger.click()
    expect(page.get_by_role("radio", name="SNMPv3", exact=True)).to_be_checked()
    expect(page.get_by_role("radio", name="SSH", exact=True)).to_be_enabled()
    expect(page.get_by_role("radio", name="API", exact=True)).to_be_disabled()
    assert submissions == []
    page.get_by_role("button", name="Test et", exact=True).click()
    expect(page.get_by_role("heading", name="Cihazda test çalışıyor…", exact=True)).to_be_visible()
    expect(page.get_by_role("radio", name="SSH", exact=True)).to_be_disabled()
    expect(page.get_by_role("heading", name="Bağlantı başarılı", exact=True)).to_be_visible()
    expect(page.locator(".connection-test-result")).to_contain_text("Fixture SNMP response")
    assert submissions == ["snmpv3"]
    page.get_by_role("radio", name="SSH", exact=True).check()
    page.get_by_role("button", name="Test et", exact=True).click()
    expect(page.get_by_role("heading", name="Bağlantı başarısız", exact=True)).to_be_visible()
    expect(page.locator(".connection-test-result")).to_contain_text("Fixture SSH authentication failed")
    assert submissions == ["snmpv3", "ssh"]
    cancelling = True
    page.get_by_role("radio", name="SNMPv3", exact=True).check()
    page.get_by_role("button", name="Test et", exact=True).click()
    page.get_by_role("button", name="Testi iptal et", exact=True).click()
    expect(page.get_by_role("heading", name="Test iptal edildi", exact=True)).to_be_visible()
    page.get_by_role("button", name="Kapat", exact=True).click()
    expect(trigger).to_be_focused()

    enabled = {"rest"}
    trigger.click()
    expect(page.get_by_role("radio", name="API", exact=True)).to_be_checked()
    expect(page.get_by_role("radio", name="SNMPv3", exact=True)).to_be_disabled()
    expect(page.get_by_role("radio", name="SSH", exact=True)).to_be_disabled()
    expect(page.get_by_text("/api/system", exact=False)).to_be_visible()
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()

    # Inspect both themes, mobile layouts, keyboard focus and modal accessibility.
    Path("artifacts").mkdir(exist_ok=True)
    violations = {}
    for theme, width, height in [
        ("light", 1440, 1000),
        ("dark", 1440, 1000),
        ("dark", 375, 812),
        ("light", 812, 375),
    ]:
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        page.set_viewport_size({"width": width, "height": height})
        trigger.click()
        expect(page.get_by_role("radio", name="API", exact=True)).to_be_checked()
        assert page.locator("body").evaluate("e => e.scrollWidth <= window.innerWidth")
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        report = page.evaluate(
            "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
        )
        violations[f"{theme}-{width}"] = [
            {"id": v["id"], "nodes": [n["target"] for n in v["nodes"]]} for v in report["violations"]
        ]
        page.screenshot(path=f"artifacts/connection-test-{theme}-{width}.png", full_page=True)
        page.keyboard.press("Escape")
    assert not any(violations.values()), violations
    assert not errors, errors
    print(
        json.dumps(
            {
                "connection_test_modal": "PASS",
                "profile_gating": True,
                "selected_protocol_only": True,
                "success_failure_cancel": True,
                "themes_and_viewports": 4,
                "axe": violations,
                "console_errors": errors,
            }
        )
    )
    browser.close()
