"""IPAM hierarchy, rack, metadata, bulk/filter workflows on a local isolated fixture."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Protocol tests remain isolated; image availability is checked separately against the manufacturer.
    page.route(
        "https://assets.ext.hpe.com/**",
        lambda route: route.fulfill(
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="40"><rect width="400" height="40" fill="#9ca3af"/><text x="20" y="25">TEST IMAGE FIXTURE</text></svg>',
        ),
    )
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
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), (
                        name,
                        width,
                        dialog.evaluate(
                            "e=>({width:e.clientWidth,scroll:e.scrollWidth,children:[...e.querySelectorAll('.rack-dialog, .rack-elevation, .rack-placement-form, .rack-image-settings')].map(x=>[x.className,x.clientWidth,x.scrollWidth])})"
                        ),
                    )
                    boxes = dialog.locator(
                        ".ipam-fields > .ipam-field input, .ipam-fields > .ipam-field select, .form-grid > .form-field > input, .form-grid > .form-field > select"
                    ).evaluate_all(
                        "els=>els.map(e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}})"
                    )
                    if boxes:
                        assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) < 1, (name, boxes)
                        if width == 375:
                            assert max(b["x"] for b in boxes) - min(b["x"] for b in boxes) < 1, (name, boxes)
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                page.screenshot(path=f"artifacts/hierarchy-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    def goto(key):
        page.goto("http://127.0.0.1:8211/#" + key)
        page.wait_for_load_state("networkidle")

    goto("sites")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="Yeni Kurum Ekle", exact=True).wait_for()
    page.get_by_role("button", name="Yeni Kurum Ekle", exact=True).click()
    page.get_by_label("Kurum adı", exact=True).fill("İkinci Kurum")
    page.get_by_label("Kurum kodu", exact=True).fill("02")
    check("institution-form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    page.get_by_role("button", name="Kuzey Kampüs", exact=True).click()
    page.get_by_role("button", name="Alt lokasyon ekle", exact=True).click()
    page.get_by_label("Lokasyon adı", exact=True).fill("Kat 1")
    check("sublocation-form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="01-000011", exact=True)).to_be_visible()
    check("sublocations")
    page.on("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Kat 1 sil", exact=True).click()
    expect(page.get_by_role("cell", name="Kat 1", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="Alt lokasyon ekle", exact=True).click()
    page.get_by_label("Lokasyon adı", exact=True).fill("Kat 2")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="01-000011", exact=True)).to_be_visible()
    goto("cabinets")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    page.get_by_label("Kabinet no", exact=True).fill("K-12")
    page.get_by_role("combobox", name="Lokasyon", exact=True).select_option(label="Kuzey Kampüs")
    page.get_by_role("combobox", name="Alt lokasyon", exact=True).select_option(label="Kat 2")
    page.get_by_label("Kapasite (U)", exact=True).fill("12")
    check("cabinet-form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    page.get_by_role("button", name="K-12", exact=True).click()
    page.get_by_role("combobox", name="Cihaz", exact=True).select_option(label="Core Switch · 6100-JL675A")
    page.get_by_label("Başlangıç U", exact=True).fill("11")
    page.get_by_role("button", name="Yerleşimi kaydet", exact=True).click()
    expect(page.get_by_role("img", name="Aruba 6100-JL675A üretici görseli", exact=True)).to_be_visible()
    check("rack")
    page.get_by_text("Üretici model görselini tanımla", exact=True).click()
    page.get_by_label("Üretici görsel URL", exact=True).fill(
        "https://assets.ext.hpe.com/is/image/hpedam/s00009458?$zoom$="
    )
    page.get_by_label("Üretici ürün sayfası URL", exact=True).fill(
        "https://buy.hpe.com/emea_middle_east/en/networking/switches/fixed-port-l3-managed-ethernet-switches/hpe-aruba-networking-cx-6100-48g-class4-poe-4sfp-370w-switch/p/jl675a"
    )
    check("manufacturer-image")
    with page.expect_response("**/api/v1/ipam/devices/*/model-image") as image_response:
        page.get_by_role("button", name="Model görselini kaydet", exact=True).click()
    assert image_response.value.status == 200
    page.keyboard.press("Escape")
    goto("prefixes")
    page.get_by_role("button", name="192.0.2.0/24 düzenle", exact=True).click()
    page.get_by_role("combobox", name="Kurum", exact=True).select_option(label="İkinci Kurum")
    assert page.get_by_role("combobox", name="Lokasyon", exact=True).locator("option").count() == 1
    page.get_by_role("combobox", name="Kurum", exact=True).select_option(label="Fixture Üniversitesi")
    page.get_by_role("combobox", name="Lokasyon", exact=True).select_option(label="Kuzey Kampüs")
    check("prefix-form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(page.get_by_role("heading", name="VLAN-10 / SERVER | 192.0.2.0/24", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name="Yalnızca kayıtlı IP’ler", exact=True).check()
    page.get_by_role("button", name="192.0.2.10 düzenle", exact=True).click()
    expect(page.get_by_label("IP adresi", exact=True)).to_have_attribute("readonly", "")
    page.get_by_role("combobox", name="Bağlı cihaz", exact=True).select_option(label="Core Switch")
    choices = page.get_by_role("combobox", name="Arayüz", exact=True).locator("option").all_text_contents()
    assert choices == ["Seçiniz", "GigabitEthernet1/0/12"], choices
    page.get_by_role("combobox", name="Arayüz", exact=True).select_option(label="GigabitEthernet1/0/12")
    page.get_by_role("combobox", name="İşletim sistemi", exact=True).select_option(label="Windows Server")
    page.get_by_role("combobox", name="Kabinet no", exact=True).select_option(label="K-12")
    page.get_by_role("combobox", name="Lokasyon", exact=True).select_option(label="Kat 2")
    check("ip-form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(
        page.get_by_role("row")
        .filter(has=page.get_by_role("checkbox", name="192.0.2.10 seç", exact=True))
        .get_by_role("cell", name="Core Switch", exact=True)
    ).to_be_visible()
    expect(
        page.get_by_role("row")
        .filter(has=page.get_by_role("checkbox", name="192.0.2.10 seç", exact=True))
        .get_by_role("cell", name="GigabitEthernet1/0/12", exact=True)
    ).to_be_visible()
    page.get_by_label("IPAM kayıtlarında ara", exact=True).fill("Windows Kat")
    expect(page.get_by_role("cell", name="Windows Server", exact=True)).to_be_visible()
    page.get_by_role("button", name="Filtreler", exact=True).click()
    page.get_by_role("button", name="Koşul ekle", exact=True).click()
    page.get_by_label("Koşul 1 alanı", exact=True).select_option("hostname")
    page.get_by_label("Koşul 1 işlemi", exact=True).select_option("not_contains")
    page.get_by_label("Koşul 1 değeri", exact=True).fill("absent")
    page.get_by_role("button", name="Koşul ekle", exact=True).click()
    page.get_by_label("Koşul 2 bağlantısı", exact=True).select_option("or")
    page.get_by_label("Koşul 2 alanı", exact=True).select_option("operating_system")
    page.get_by_label("Koşul 2 değeri", exact=True).fill("Windows")
    check("filters")
    page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    page.get_by_role("button", name="Sütunlar", exact=True).click()
    page.get_by_role("checkbox", name="MAC adresi", exact=True).uncheck()
    check("columns")
    page.get_by_role("button", name="Sütunları uygula", exact=True).click()
    expect(page.get_by_role("columnheader", name="MAC adresi", exact=True)).not_to_be_visible()
    page.get_by_role("checkbox", name="192.0.2.10 seç", exact=True).check()
    page.get_by_role("region", name="Seçilen IP işlemleri", exact=True).get_by_role(
        "button", name="Düzenle", exact=True
    ).click()
    page.get_by_role("checkbox", name="Hostname değiştir", exact=True).check()
    page.get_by_label("Hostname", exact=True).fill("bulk-server")
    check("bulk")
    page.get_by_role("button", name="Değişiklikleri uygula", exact=True).click()
    expect(page.get_by_role("cell", name="bulk-server", exact=True)).to_be_visible()
    check("address-table")
    page.get_by_role("button", name="Ağ bloğu ayarları", exact=True).click()
    assert page.get_by_text("Yetkili keşif kapsamı", exact=True).count() == 0
    page.get_by_role(
        "checkbox", name="Bu ağ bloğunda keşif ve ping işlemleri yetkilendirilmiştir", exact=True
    ).uncheck()
    expect(page.get_by_role("checkbox", name="IP durumunu düzenli kontrol et", exact=True)).to_be_disabled()
    check("authorization")
    page.get_by_role("button", name="Ayarları kaydet", exact=True).click()
    assert not errors, errors
    assert not any(reports.values()), reports
    print(json.dumps({"workflows": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
