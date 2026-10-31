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
    expected_menu = [
        "Ağ blokları",
        "IP adresleri",
        "VLAN alanları",
        "Kabinetler",
        "İşletim Sistemi",
        "Lokasyon",
        "DNS Sunucuları",
        "Yönlendirme alanları",
    ]
    group = page.locator(".nav-group").filter(
        has=page.get_by_role("button", name="IP adres yönetimi", exact=True)
    )
    assert group.locator(".nav-item").all_text_contents() == expected_menu
    group.get_by_role("button", name="IP adres yönetimi", exact=True).click()
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        if width == 375:
            page.get_by_role("button", name="Menüyü aç", exact=True).click()
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            boxes = group.locator(".nav-item").evaluate_all(
                "els=>els.map(e=>{let b=e.getBoundingClientRect();let t=e.querySelector('span').getBoundingClientRect();let i=e.querySelector('svg').getBoundingClientRect();return {x:b.x,w:b.width,h:b.height,tx:t.x,cy:t.y+t.height/2,iy:i.y+i.height/2}})"
            )
            assert max(b["x"] for b in boxes) - min(b["x"] for b in boxes) < 1
            assert max(b["w"] for b in boxes) - min(b["w"] for b in boxes) < 1
            assert max(b["tx"] for b in boxes) - min(b["tx"] for b in boxes) < 1
            assert all(abs(b["cy"] - b["iy"]) < 1 for b in boxes)
            expect(group.get_by_role("button", name="Yönlendirme alanları", exact=True)).to_be_visible()
            page.screenshot(path=f"artifacts/ipam-menu-{width}-{theme}.png")
        if width == 375:
            page.get_by_role("button", name="Menüyü kapat", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    check("blocks")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(page.get_by_role("cell", name="192.0.2.99", exact=True)).to_be_visible()
    check("addresses")
    page.get_by_role("button", name="192.0.2.11 ata", exact=True).click()
    page.get_by_role("combobox", name="İşletim sistemi", exact=True).select_option(label="Windows Server")
    page.get_by_role("combobox", name="Kabinet no", exact=True).select_option(label="K-04")
    page.get_by_role("combobox", name="Lokasyon", exact=True).select_option(label="Kuzey Kampüs")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("button", name="192.0.2.11", exact=True)).to_be_visible()
    page.get_by_role("button", name="192.0.2.11 düzenle", exact=True).click()
    expect(page.get_by_label("İşletim sistemi", exact=True)).to_have_value("Windows Server")
    expect(page.get_by_label("Kabinet no", exact=True)).to_have_value("K-04")
    check("ip-metadata-form")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Sonraki 100 adres", exact=True).click()
    expect(page.get_by_role("cell", name="192.0.2.100", exact=True)).to_be_visible()
    page.get_by_role("button", name="Önceki", exact=True).click()
    page.get_by_role("button", name="Ağ blokları", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
    page.get_by_label("IP kullanım uyarı eşiği (%)", exact=True).fill("65")
    page.get_by_role("combobox", name="VLAN’ın bulunduğu cihaz", exact=True).select_option(
        label="Core Switch"
    )
    page.get_by_label("IP durumunu düzenli kontrol et", exact=True).check()
    check("settings")
    page.get_by_role("button", name="Ayarları kaydet", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
    expect(page.get_by_label("IP kullanım uyarı eşiği (%)", exact=True)).to_have_value("65")
    expect(page.get_by_label("IP durumunu düzenli kontrol et", exact=True)).to_be_checked()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("button", name="192.0.2.10", exact=True).click()
    expect(page.get_by_text("Ubuntu Linux 24.04", exact=True).first).to_be_visible()
    check("detail")
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
    expect(page.get_by_label("Parola", exact=True)).to_have_count(0)
    page.get_by_label("Entegrasyon adı", exact=True).fill("Windows DHCP")
    page.get_by_role("button", name="Entegrasyonu kaydet", exact=True).click()
    expect(page.get_by_role("button", name="Windows DHCP düzenle", exact=True)).to_be_visible()
    assert not errors, errors
    assert not any(reports.values()), reports
    print(json.dumps({"workflows": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
