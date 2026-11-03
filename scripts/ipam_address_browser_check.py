"""Real enqueue/worker/detail flow against fake protocols, with refresh and a11y checks."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = f"http://127.0.0.1:{os.environ.get('NETRIX_ADDRESS_FIXTURE_PORT', '8242')}"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    writes, errors, sockets = [], [], []
    page.route_web_socket("**/api/v1/ws", lambda s: sockets.append(s))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "request",
        lambda r: (
            writes.append(r.url)
            if r.method == "POST" and ("/ipam/" in r.url or r.url.endswith("/sync"))
            else None
        ),
    )
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("button", name="192.0.2.12", exact=True).click()
    dialog = page.get_by_role("dialog")
    button = dialog.get_by_role("button", name="192.0.2.12 için tara", exact=True)
    expect(button).to_be_enabled()
    assert not writes
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert button.bounding_box()["height"] >= (44 if width <= 640 else 40) - 0.1, (
                width,
                button.bounding_box(),
            )
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))"
            )
            dialog.screenshot(path=f"/tmp/netrix-address-{width}-{theme}.png")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/scan")) as pending:
        button.click()
    assert pending.value.status == 202
    job = pending.value.json()
    assert job["kind"] == "ipam_address_scan" and job["total"] == 1
    assert job["result"]["address_scope"][0] == "192.0.2.12"
    expect(button).to_be_disabled()
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        dialog.screenshot(path=f"/tmp/netrix-address-queued-{width}.png")
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="192.0.2.12", exact=True).click()
    expect(button).to_be_disabled()
    expect(dialog).to_contain_text("Kuyrukta")
    assert len(writes) == 1
    outcome = page.request.post(BASE + "/fixture/run-address-job", headers={"X-Netrix-Request": "1"}).json()
    assert outcome["job_id"] == job["id"]
    assert outcome["pinged"] == outcome["resolved"] == ["192.0.2.12"]
    sockets[-1].send(json.dumps({"type": "ipam_update", "vlan_id": job["result"]["address_scope"][2]}))
    expect(dialog).to_contain_text("Tamamlandı", timeout=6000)
    expect(dialog.locator(".ipam-summary")).to_contain_text("scanned-12.example.test")
    expect(button).to_be_enabled()
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    row = page.get_by_role("row").filter(has=page.get_by_role("button", name="192.0.2.12", exact=True))
    other = page.get_by_role("row").filter(has=page.get_by_role("button", name="192.0.2.11", exact=True))
    expect(row).to_contain_text("scanned-12.example.test")
    expect(other).to_contain_text("MANUAL-FW-11")
    page.get_by_role("button", name="192.0.2.12", exact=True).click()
    button.click()
    expect(button).to_be_disabled()
    dialog.get_by_role("button", name="İptal et", exact=True).click()
    expect(dialog).to_contain_text("IP taraması iptal edildi")
    expect(button).to_be_enabled()
    assert len(writes) == 2 and not errors, (writes, errors)
    print(
        "PASS: one-IP queue/reopen/dedupe, fake worker probes only selected IP, pushed detail/list results, other IP intact, desktop/mobile/landscape and axe"
    )
    browser.close()
