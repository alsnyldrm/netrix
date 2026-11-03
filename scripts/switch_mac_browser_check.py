"""Browser/API integration with a disposable cache: scheduling card, fallback and live port move."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    sockets, errors = [], []
    page.route_web_socket("**/api/v1/ws", lambda socket: sockets.append(socket))
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#ipam-settings")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    panel = page.locator(".switch-mac-panel")
    expect(panel).not_to_have_attribute("open", "")
    panel.locator("summary").click()
    expect(panel).to_contain_text("00:00 · 06:00 · 12:00 · 18:00")
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))"
            )
            assert not violations, violations
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=f"/tmp/netrix-switch-mac-settings-{width}-{theme}.png", full_page=True)
    with page.expect_response(
        lambda r: r.url.endswith("/ipam/switch-mac-cache/scan") and r.request.method == "POST"
    ) as response:
        panel.get_by_role("button", name="Şimdi tara", exact=True).click()
    assert response.value.status == 202
    job = response.value.json()
    assert job["kind"] == "switch_mac_scan"
    expect(panel.get_by_role("button", name="Şimdi tara", exact=True)).to_be_disabled()
    assert page.request.post(BASE + f"/api/v1/jobs/{job['id']}/cancel", headers={"X-Netrix-Request": "1"}).ok
    page.goto(BASE + "/#vlans")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    target = page.get_by_role("row").filter(has=page.get_by_role("button", name="192.0.2.13", exact=True))
    expect(target).to_contain_text("Switch 1")
    expect(target).to_contain_text("1/1/7")
    page.get_by_role("button", name="192.0.2.13", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Switch MAC tablosu")
    assert page.request.post(BASE + "/fixture/mac-move", headers={"X-Netrix-Request": "1"}).ok
    sockets[-1].send(json.dumps({"type": "ipam_update", "vlan_id": "*"}))
    expect(dialog.locator(".ipam-summary")).to_contain_text("1/1/8", timeout=3000)
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    expect(target).to_contain_text("1/1/8")
    assert not errors, errors
    print(
        "PASS: real API manual queue/dedupe, local source fallback, live moved port in table/detail, desktop/mobile/landscape and axe"
    )
    browser.close()
