"""Check removed controls, responsive geometry and accessibility on local fixtures."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(bypass_csp=True, reduced_motion="reduce")
    errors, requests, reports = [], [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto("http://127.0.0.1:8211/")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for key in ("overview", "devices", "interfaces", "addresses", "settings", "monitoring"):
            page.goto("http://127.0.0.1:8211/#" + key)
            page.wait_for_load_state("networkidle")
            assert "Trafik gözlemevi" not in page.content()
            assert "Networkü izle" not in page.content()
            assert "Zamanlanmış izleme" not in page.content()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{key}-{width}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>v.id)"
            )
            if key == "devices":
                page.get_by_role("button", name="Yeni kayıt", exact=True).click()
                dialog = page.get_by_role("dialog")
                expect(dialog).to_be_visible()
                assert "İzleme aralığı" not in dialog.inner_text()
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                page.screenshot(path=f"/tmp/netrix-removal-device-form-{width}.png")
                page.keyboard.press("Escape")
            if key == "addresses":
                page.get_by_role("button", name="192.0.2.10 IP ayrıntıları", exact=True).click()
                dialog = page.get_by_role("dialog")
                expect(dialog.get_by_role("heading", name="Kaynak gözlemleri")).to_be_visible()
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                page.screenshot(path=f"/tmp/netrix-removal-address-{width}.png")
                page.keyboard.press("Escape")
            page.screenshot(path=f"/tmp/netrix-removal-{key}-{width}.png")
    assert not errors, errors
    assert not any("/traffic" in url or "/addresses/" in url and url.endswith("/live") for url in requests)
    assert not any(reports.values()), reports
    print(json.dumps({"screens": reports, "console_errors": errors, "traffic_requests": 0}))
    browser.close()
