"""Save the supplied CDN image and Fortinet source with browser CSP enabled."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

IMAGE = "https://cdn.blueally.com/avfirewalls/images/fortigate/fg-600f.png"
SOURCE = "https://docs.fortinet.com/document/fortigate/8.0.2/hardware-acceleration/589036/fortigate-600f-and-601f-fast-path-architecture"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.route(
        IMAGE,
        lambda route: route.fulfill(
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="40"><rect width="400" height="40" fill="#cbd5e1"/><text x="20" y="25">600F TEST FIXTURE</text></svg>',
        ),
    )
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        "window.cspErrors=[]; document.addEventListener('securitypolicyviolation', e=>window.cspErrors.push(e.violatedDirective));"
    )
    page.goto("http://127.0.0.1:8211/#cabinets")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    vrf = page.request.get("http://127.0.0.1:8211/api/v1/vrfs").json()["items"][0]["id"]
    site = page.request.get("http://127.0.0.1:8211/api/v1/sites").json()["items"][0]["id"]
    headers = {"X-Netrix-Request": "1"}
    response = page.request.post(
        "http://127.0.0.1:8211/api/v1/devices",
        headers=headers,
        data={
            "name": "Fixture Firewall",
            "management_ip": "192.0.2.44",
            "vrf_id": vrf,
            "kind": "firewall",
            "vendor": "Fortinet",
            "model": "FGT_600F",
        },
    )
    assert response.status == 201, response.text()
    response = page.request.post(
        "http://127.0.0.1:8211/api/v1/cabinets",
        headers=headers,
        data={"name": "Photo Rack", "site_id": site, "units": 42},
    )
    assert response.status == 201, response.text()
    page.reload()
    page.get_by_role("button", name="Photo Rack", exact=True).click()
    page.get_by_role("combobox", name="Cihaz", exact=True).select_option(label="Fixture Firewall · FGT_600F")
    page.get_by_label("Başlangıç U", exact=True).fill("42")
    page.get_by_role("button", name="Yerleşimi kaydet", exact=True).click()
    page.get_by_text("Üretici model görselini tanımla", exact=True).click()
    url = page.get_by_label("Üretici görsel URL", exact=True)
    source = page.get_by_label("Üretici ürün sayfası URL", exact=True)
    expect(url).to_be_enabled()
    url.fill("https://example.test/wrong.png")
    source.fill(SOURCE)
    page.get_by_role("button", name="Model görselini kaydet", exact=True).click()
    alert = page.locator(".rack-image-settings").get_by_role("alert")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("cdn.blueally.com")
    expect(url).to_have_value("https://example.test/wrong.png")
    url.fill(IMAGE)
    page.get_by_role("button", name="Model görselini kaydet", exact=True).click()
    expect(page.get_by_text("Model görseli ve ürün sayfası kaydedildi.", exact=True)).to_be_visible()
    img = page.get_by_role("img", name="Fortinet FGT_600F üretici görseli", exact=True)
    expect(img).to_be_visible()
    page.wait_for_function("()=>document.querySelector('.rack-device img')?.naturalWidth > 0")
    expect(page.get_by_role("link", name="Üretici kaynağı", exact=True)).to_have_attribute("href", SOURCE)
    for width, height in ((1440, 1000), (375, 812)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            page.get_by_role("button", name="Model görselini kaydet", exact=True).scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            boxes = page.locator(".rack-image-settings input").evaluate_all(
                "es=>es.map(e=>{const b=e.getBoundingClientRect();return {x:b.x,width:b.width,height:b.height}})"
            )
            assert (
                abs(boxes[0]["x"] - boxes[1]["x"]) < 1
                and abs(boxes[0]["width"] - boxes[1]["width"]) < 1
                and abs(boxes[0]["height"] - boxes[1]["height"]) < 1
            )
            page.evaluate(Path("frontend/node_modules/axe-core/axe.min.js").read_text())
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/model-image-{width}-{theme}.png")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Photo Rack", exact=True).click()
    page.get_by_role("button", name="Fixture Firewall yerleşimini düzenle", exact=True).click()
    page.get_by_text("Üretici model görselini tanımla", exact=True).click()
    expect(url).to_have_value(IMAGE)
    expect(source).to_have_value(SOURCE)
    page.get_by_role("combobox", name="Cihaz", exact=True).select_option(label="Core Switch · 6100-JL675A")
    expect(url).not_to_have_value(IMAGE)
    page.get_by_role("combobox", name="Cihaz", exact=True).select_option(label="Fixture Firewall · FGT_600F")
    expect(url).to_have_value(IMAGE)
    assert not errors and not any(reports.values()), (errors, reports)
    assert page.evaluate("window.cspErrors") == []
    print(
        json.dumps({"save_reload_switch": "PASS", "CSP": "enabled", "axe": reports, "console_errors": errors})
    )
    browser.close()
