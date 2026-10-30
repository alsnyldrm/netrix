"""IPAM workflows, keyboard controls, layout and accessibility on isolated fixtures."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    reports = {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    Path("artifacts").mkdir(exist_ok=True)

    def check(name):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                dialog = page.get_by_role("dialog")
                if dialog.count():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                    fields = dialog.locator(".ipam-fields .ipam-field input, .ipam-fields .ipam-field select")
                    boxes = fields.evaluate_all(
                        "els=>els.map(e=>{let b=e.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}})"
                    )
                    if boxes:
                        assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) < 1
                        if width == 375:
                            assert max(b["x"] for b in boxes) - min(b["x"] for b in boxes) < 1
                        elif len(boxes) >= 2:
                            assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1
                            assert abs(boxes[0]["w"] - boxes[1]["w"]) < 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                page.screenshot(path=f"artifacts/ipam-{name}-{width}-{theme}.png", full_page=False)
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).wait_for()
    check("blocks")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(page.get_by_role("cell", name="192.0.2.99", exact=True)).to_be_visible()
    check("addresses")
    page.get_by_role("button", name="192.0.2.11 ata", exact=True).click()
    page.get_by_label("İşletim sistemi", exact=True).fill("Windows Server")
    page.get_by_label("Kabinet no", exact=True).fill("K-05")
    page.get_by_label("Lokasyon", exact=True).fill("Kat 2")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("button", name="192.0.2.11", exact=True)).to_be_visible()
    page.get_by_role("button", name="192.0.2.11 düzenle", exact=True).click()
    expect(page.get_by_label("İşletim sistemi", exact=True)).to_have_value("Windows Server")
    expect(page.get_by_label("Kabinet no", exact=True)).to_have_value("K-05")
    check("ip-metadata-form")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Sonraki 100 adres", exact=True).click()
    expect(page.get_by_role("cell", name="192.0.2.100", exact=True)).to_be_visible()
    page.get_by_role("button", name="Önceki", exact=True).click()
    page.get_by_role("button", name="Ağ bloğu ayarları", exact=True).click()
    page.get_by_label("IP kullanım uyarı eşiği (%)", exact=True).fill("65")
    page.get_by_role("combobox", name="VLAN’ın bulunduğu cihaz", exact=True).select_option(
        label="Core Switch"
    )
    page.get_by_label("IP durumunu düzenli kontrol et", exact=True).check()
    check("settings")
    page.get_by_role("button", name="Ayarları kaydet", exact=True).click()
    page.get_by_role("button", name="Ağ bloğu ayarları", exact=True).click()
    expect(page.get_by_label("IP kullanım uyarı eşiği (%)", exact=True)).to_have_value("65")
    expect(page.get_by_label("IP durumunu düzenli kontrol et", exact=True)).to_be_checked()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="192.0.2.10", exact=True).click()
    expect(page.get_by_text("Ubuntu Linux 24.04", exact=True).first).to_be_visible()
    page.get_by_role("combobox", name="İzlenecek bağlantı", exact=True).select_option(index=2)
    check("detail")
    # Verify five-second polling uses fresh provider timestamps, no physical network calls.
    calls = {"live": 0, "traffic": 0, "cancel": 0}

    def live(route):
        calls["live"] += 1
        route.fulfill(json={"id": "live-fixture", "status": "running"})

    source_id = page.get_by_role("combobox", name="İzlenecek bağlantı", exact=True).input_value()[2:]

    def traffic(route):
        calls["traffic"] += 1
        route.fulfill(
            json={
                "items": [
                    {
                        "id": str(i),
                        "source_key": "vcenter:" + source_id + ":vm-1:4000",
                        "sampled_at": f"2026-10-31T10:00:{i * 20:02d}+00:00",
                        "interval_seconds": 20,
                        "in_bps": 1000000 * i,
                        "out_bps": 500000 * i,
                    }
                    for i in range(1, 3)
                ]
            }
        )

    page.route("**/api/v1/ipam/addresses/*/live", live)
    page.route(
        "**/api/v1/jobs/live-fixture", lambda r: r.fulfill(json={"id": "live-fixture", "status": "running"})
    )
    page.route("**/api/v1/ipam/addresses/*/traffic", traffic)

    def cancel(route):
        calls["cancel"] += 1
        route.fulfill(json={"id": "live-fixture", "status": "cancelled"})

    page.route("**/api/v1/jobs/live-fixture/cancel", cancel)
    page.get_by_role("button", name="Networkü izle", exact=True).last.click()
    expect(page.get_by_role("img", name="Giriş ve çıkış trafik grafiği")).to_be_visible()
    page.wait_for_timeout(5400)
    assert calls["traffic"] >= 2 and calls["live"] == 1, calls
    check("live")
    page.get_by_role("button", name="İzlemeyi durdur", exact=True).click()
    page.wait_for_timeout(200)
    assert calls["cancel"] == 1
    page.keyboard.press("Escape")
    page.goto("http://127.0.0.1:8211/#integrations")
    page.get_by_role("button", name="Entegrasyon ekle", exact=True).click()
    page.get_by_label("Entegrasyon adı", exact=True).fill("Kampüs DHCP")
    page.get_by_role("combobox", name="Entegrasyon türü", exact=True).select_option("windows_dhcp")
    expect(page.get_by_label("HTTPS portu", exact=True)).to_have_value("5986")
    page.get_by_label("Sunucu adı veya IP", exact=True).fill("dhcp.example.test")
    page.get_by_label("Kullanıcı", exact=True).fill("EXAMPLE\\reader")
    page.get_by_label("Parola", exact=True).fill("fixture-only-password")
    page.get_by_role("checkbox", name="192.0.2.0/24 · Global").check()
    check("integration-form")
    page.get_by_role("button", name="Entegrasyonu kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="dhcp.example.test:5986", exact=True)).to_be_visible()
    check("integrations")
    page.get_by_role("button", name="Kampüs DHCP düzenle", exact=True).click()
    expect(page.get_by_label("Parola", exact=True)).to_have_value("")
    page.get_by_label("Entegrasyon adı", exact=True).fill("Windows DHCP")
    page.get_by_role("button", name="Entegrasyonu kaydet", exact=True).click()
    expect(page.get_by_role("button", name="Windows DHCP düzenle", exact=True)).to_be_visible()
    assert not errors, errors
    assert not any(reports.values()), reports
    print(json.dumps({"workflows": "PASS", "calls": calls, "axe": reports, "console_errors": errors}))
    browser.close()
