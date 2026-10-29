"""Local API fixtures: device SSH trust checkbox persistence, layout and accessibility."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8203")
assert BASE.startswith("http://127.0.0.1:"), "Local fixture required"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    errors, saves = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    device = {
        "id": "device-1",
        "name": "Fixture firewall",
        "management_ip": "192.0.2.1",
        "vrf_id": "vrf-1",
        "adapter": "fortios",
        "kind": "firewall",
        "config_credential_id": "ssh-1",
        "config_port": 1234,
        "ssh_trust_host_key": False,
        "lifecycle_status": "active",
    }

    def api(route):
        path = urlparse(route.request.url).path.removeprefix("/api/v1/")
        if path == "auth/me":
            data = {"id": "user-1", "display_name": "Browser tester", "role": "admin"}
        elif path == "dashboard":
            data = {"counts": {}}
        elif path == "devices/device-1" and route.request.method == "PUT":
            saves.append(route.request.post_data_json)
            device.update(saves[-1])
            data = device
        else:
            rows = {
                "devices": [device],
                "vrfs": [{"id": "vrf-1", "name": "Global"}],
                "credentials": [{"id": "ssh-1", "name": "Fixture SSH", "protocol": "ssh"}],
            }.get(path, [])
            data = {"items": rows, "total": len(rows)}
        route.fulfill(json=data)

    page.route("**/api/v1/**", api)
    page.goto(BASE + "/#devices")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    trust = page.get_by_role("checkbox", name="Anahtara güven", exact=True)
    expect(trust).not_to_be_checked()
    page.get_by_label("Konfigürasyon adaptörü", exact=False).select_option("rest")
    expect(trust).to_have_count(0)
    page.get_by_label("Konfigürasyon adaptörü", exact=False).select_option("fortios")
    expect(trust).not_to_be_checked()
    page.keyboard.press("Escape")
    edit = page.get_by_role("button", name="Kaydı düzenle", exact=True)
    for enabled in (True, False):
        edit.click()
        expect(trust).to_be_checked(checked=not enabled)
        trust.set_checked(enabled)
        page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert saves[-1]["ssh_trust_host_key"] is enabled
    violations = {}
    Path("artifacts").mkdir(exist_ok=True)
    for theme, width, height in [
        ("light", 1440, 1000),
        ("dark", 1440, 1000),
        ("dark", 375, 812),
        ("light", 812, 375),
    ]:
        page.evaluate("t => document.documentElement.dataset.theme = t", theme)
        page.set_viewport_size({"width": width, "height": height})
        edit.click()
        trust.scroll_into_view_if_needed()
        trust.focus()
        trust.press("Space")
        expect(trust).to_be_checked()
        assert trust.evaluate("e => !!document.getElementById(e.getAttribute('aria-describedby'))")
        alignment = trust.evaluate("""e => {
          const label = e.closest('label'), text = label.querySelector('span'), hint = label.querySelector('small');
          const a = e.getBoundingClientRect(), b = text.getBoundingClientRect(), c = hint.getBoundingClientRect();
          return {center: Math.abs(a.y + a.height/2 - b.y - b.height/2), hint: Math.abs(b.x - c.x), edge: Math.abs(a.x - label.getBoundingClientRect().x)};
        }""")
        assert alignment["center"] <= 1 and alignment["hint"] <= 1 and alignment["edge"] <= 1, alignment
        assert page.get_by_role("dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        report = page.evaluate(
            "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
        )
        violations[f"{theme}-{width}"] = [v["id"] for v in report["violations"]]
        page.screenshot(path=f"artifacts/ssh-trust-{theme}-{width}.png", full_page=True)
        page.keyboard.press("Escape")
    assert not any(violations.values()), violations
    assert not errors, errors
    print(
        json.dumps(
            {
                "ssh_trust_form": "PASS",
                "create_edit_toggle_persistence": True,
                "alignment": "PASS",
                "axe": violations,
                "console_errors": errors,
            }
        )
    )
    browser.close()
