"""VLAN-owned IPAM and configuration UI checks on isolated local fixtures."""

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

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                dialogs = page.get_by_role("dialog")
                if dialogs.count():
                    assert dialogs.last.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                reports[f"{name}-{width}-{theme}"] = violations
                page.screenshot(path=f"/tmp/netrix-vlan-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    def go(key):
        page.goto("http://127.0.0.1:8215/#" + key)
        page.wait_for_load_state("networkidle")

    go("vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="VLAN alanları", exact=True)).to_be_visible()
    group = page.locator(".nav-group").filter(
        has=page.get_by_role("button", name="IP adres yönetimi", exact=True)
    )
    assert group.locator(".nav-item").all_text_contents()[0] == "VLAN alanları"
    assert "IP adresleri" not in group.inner_text() and "Ağ blokları" not in group.inner_text()
    inventory = page.locator(".nav-group").filter(has=page.get_by_role("button", name="Envanter", exact=True))
    assert inventory.get_by_role("button", name="Ağ keşfi", exact=True, include_hidden=True).count() == 1
    operation = page.locator(".nav-group").filter(
        has=page.get_by_role("button", name="Operasyon", exact=True)
    )
    assert (
        operation.get_by_role("button", name="Görev merkezi", exact=False, include_hidden=True).count() == 1
    )
    assert (
        operation.get_by_role("button", name="Değişiklik günlüğü", exact=True, include_hidden=True).count()
        == 1
    )
    check("vlan-list")
    page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
    check("vlan-settings")
    assert "envanter /" not in page.get_by_role("dialog").inner_text()
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    for label in (
        "IP bloğu / CIDR",
        "DNS sunucusu",
        "IP kullanım uyarı eşiği (%)",
        "Ping aralığı (saniye)",
        "Yeni sunucu keşif aralığı (saniye)",
        "IP durumunu düzenli kontrol et",
        "Yeni sunucuları düzenli ekle",
        "Kurum",
        "Lokasyon",
        "Açıklama",
    ):
        expect(page.get_by_role("dialog").get_by_label(label, exact=True)).to_be_visible()
    assert page.get_by_label("Keşif kapsamı", exact=True).count() == 0
    check("vlan-form")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="192.0.2.10", exact=True)).to_be_visible()
    check("vlan-addresses")
    go("discovery")
    check("inventory-discovery")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    expect(page.get_by_label("VLAN ID", exact=True)).to_be_visible()
    check("inventory-discovery-form")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    go("cabinets")
    page.get_by_role("button", name="K-01", exact=True).click()
    page.get_by_role("combobox", name="Yerleşim kaynağı", exact=True).select_option("ipam")
    page.get_by_role("combobox", name="VLAN", exact=True).select_option(index=1)
    options = page.get_by_role("combobox", name="IP adresi / Hostname", exact=True)
    expect(options.locator("option")).to_have_count(2)
    check("rack-vlan-picker")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    go("integrations")
    assert "Yetkili ağ" not in page.inner_text("main")
    page.get_by_role("button", name="Entegrasyon ekle", exact=True).click()
    check("integration-form")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    go("configuration")
    expect(page.get_by_role("heading", name="Cihaz Konfigürasyonları")).to_be_visible()
    assert "Yedekler ve aktif config yalnızca SSH" not in page.content()
    page.get_by_role("button", name="Switch 1", exact=True).click()
    expect(page.get_by_text("Base config", exact=True).first).to_be_visible()
    check("config-history")
    page.locator(".page-actions").get_by_role("button", name="Karşılaştır", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Karşılaştır", exact=True).click()
    expect(page.locator(".config-editor")).to_have_count(2)
    check("config-popup")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    go("backup-compare")
    page.get_by_role("button", name="Önce cihaz seç", exact=True).click()
    for i in range(1, 5):
        page.get_by_role("dialog").get_by_label(f"Switch {i}", exact=False).check()
    page.get_by_role("button", name="Seçimi uygula", exact=True).click()
    page.locator("main").get_by_role("button", name="Karşılaştır", exact=True).click()
    expect(page.locator(".config-editor")).to_have_count(4)
    check("config-four")
    go("backup-changes")
    check("config-changes")
    page.get_by_role("button", name="Onayla", exact=True).first.click()
    page.get_by_role("dialog").get_by_role("button", name="Onayla", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Onayla", exact=True)).to_have_count(3)
    assert not errors, errors
    assert not any(reports.values()), reports
    print(json.dumps({"browser": "PASS", "views": len(reports), "axe": reports, "console_errors": errors}))
    browser.close()
