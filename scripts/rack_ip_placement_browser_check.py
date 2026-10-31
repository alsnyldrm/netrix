"""Mix central inventory and VLAN/IP endpoints in one rack, using isolated fixture data."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.route("https://assets.ext.hpe.com/**", lambda route: route.abort())
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#cabinets")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="K-04", exact=True).click()
    page.get_by_role("combobox", name="Cihaz", exact=True).select_option(label="Core Switch · 6100-JL675A")
    page.get_by_label("Başlangıç U", exact=True).fill("12")
    page.get_by_role("button", name="Yerleşimi kaydet", exact=True).click()
    expect(page.get_by_role("button", name="Core Switch yerleşimini düzenle", exact=True)).to_be_attached()
    source = page.get_by_role("combobox", name="Yerleşim kaynağı", exact=True)
    source.select_option("ipam")
    prefix = page.get_by_role("combobox", name="VLAN / Ağ bloğu", exact=True)
    prefix.select_option(index=1)
    search = page.get_by_label("IP veya hostname ara", exact=True)
    search.fill("bond-server")
    ips = page.get_by_role("combobox", name="IP adresi / Hostname", exact=True)
    expect(ips.locator("option")).to_have_count(2)
    ips.select_option(index=1)
    expect(page.get_by_label("Cihaz adı", exact=True)).to_have_value("bond-server")
    page.get_by_label("Cihaz adı", exact=True).fill("SV-ID-01")
    expect(page.get_by_role("combobox", name="Cihaz türü", exact=True)).to_have_value("server")
    expect(
        page.get_by_role("combobox", name="Cihaz türü", exact=True).locator("option", has_text="Storage")
    ).to_have_count(1)
    expect(
        page.get_by_role("combobox", name="Cihaz türü", exact=True).locator("option", has_text="SAN Switch")
    ).to_have_count(1)
    page.get_by_label("Cihaz yüksekliği (U)", exact=True).fill("2")
    page.get_by_role("button", name="IP adresinden yerleştir", exact=True).click()
    expect(page.get_by_text("SV-ID-01 kabinet yerleşimi kaydedildi.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="SV-ID-01 yerleşimini düzenle", exact=True)).to_be_attached()
    expect(page.get_by_role("button", name="Core Switch yerleşimini düzenle", exact=True)).to_be_attached()
    expect(page.get_by_label("Cihaz adı", exact=True)).to_be_disabled()
    # Repeating the placement reuses the same device.
    page.get_by_role("button", name="IP adresinden yerleştir", exact=True).click()
    expect(page.get_by_text("SV-ID-01 kabinet yerleşimi kaydedildi.", exact=True)).to_be_visible()
    devices = page.request.get("http://127.0.0.1:8211/api/v1/devices?limit=200").json()["items"]
    assert len([d for d in devices if d["management_ip"] == "192.0.2.65"]) == 1
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            page.get_by_role(
                "button", name="IP adresinden yerleştir", exact=True
            ).scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            boxes = page.locator(".rack-ip-form > label input, .rack-ip-form > label select").evaluate_all(
                "es=>es.map(e=>{const b=e.getBoundingClientRect();return {height:b.height,width:b.width}})"
            )
            assert max(b["height"] for b in boxes) - min(b["height"] for b in boxes) < 1
            assert max(b["width"] for b in boxes) - min(b["width"] for b in boxes) < 1
            page.evaluate(Path("frontend/node_modules/axe-core/axe.min.js").read_text())
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/rack-ip-form-{width}-{theme}.png")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="K-04", exact=True).click()
    edit = page.get_by_role("button", name="SV-ID-01 yerleşimini düzenle", exact=True)
    edit.click()
    expect(page.get_by_label("Başlangıç U", exact=True)).to_have_value("1")
    expect(page.get_by_label("Cihaz yüksekliği (U)", exact=True)).to_have_value("2")
    expect(page.get_by_role("combobox", name="Cihaz", exact=True)).to_have_value(
        next(d["id"] for d in devices if d["management_ip"] == "192.0.2.65")
    )
    assert not errors and not any(reports.values()), (errors, reports)
    print(json.dumps({"mixed_rack_ipam_inventory_reuse": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
