"""Room fields, cabinet grouping, inventory position and desktop/mobile checks."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8215/#cabinets")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_role("columnheader", name="Oda ismi", exact=True)).to_be_visible()
    expect(page.get_by_role("row").filter(has_text="Sunucu Odası")).to_contain_text("Fixture Üniversitesi")

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.wait_for_timeout(350)
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                for dialog in page.get_by_role("dialog").all():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                assert not violations, (name, width, theme, violations)
                page.screenshot(path=f"/tmp/netrix-rooms-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    expect(page.get_by_role("checkbox")).to_have_count(0)
    expect(page.get_by_role("columnheader", name="İşlemler", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Seçilenleri sil", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="Kabinetleri aç", exact=True)).to_have_count(0)
    search = page.get_by_label("Kat ve odalarda ara", exact=True)
    table = page.get_by_role("region", name="Katlara göre kabinet tablosu", exact=True)
    expect(table.get_by_role("columnheader")).to_have_text(
        ["Kat", "Bölüm", "Oda ismi", "Lokasyon", "Kurum", "Kabinet sayısı"]
    )
    expect(table.locator("tbody")).to_have_count(3)
    assert table.locator("tbody").evaluate_all("es=>es.map(e=>e.getAttribute('aria-label'))") == [
        "Kat L-0",
        "Kat L-2",
        "Kat L-10",
    ]
    floor = table.locator('tbody[aria-label="Kat L-0"]')
    expect(floor.get_by_role("rowheader", name="L-0", exact=True)).to_have_attribute("rowspan", "2")
    assert floor.get_by_role("button").all_text_contents() == ["Sunucu Odası", "Arşiv Odası"]
    check("floors")
    search.fill("L-0 B")
    expect(table.get_by_role("button", name="Arşiv Odası", exact=True)).to_be_visible()
    expect(table.get_by_role("button", name="Sunucu Odası", exact=True)).to_have_count(0)
    expect(table.get_by_role("rowheader", name="L-0", exact=True)).to_have_attribute("rowspan", "1")
    search.fill("sunucu kuzey")
    expect(page.get_by_role("button", name="Sunucu Odası", exact=True)).to_be_visible()
    search.fill("eşleşmeyen oda")
    expect(page.get_by_role("button", name="Sunucu Odası", exact=True)).to_have_count(0)
    expect(page.get_by_text("Arama veya filtrelere uygun kayıt yok.", exact=False)).to_be_visible()
    search.fill("")
    page.get_by_role("button", name="Filtreler", exact=True).click()
    filters = page.get_by_role("dialog").last
    filters.get_by_role("button", name="Koşul ekle", exact=True).click()
    expect(filters.get_by_label("Koşul 1 alanı", exact=True).locator("option")).to_have_text(
        ["Kat", "Bölüm", "Oda ismi", "Lokasyon", "Kurum", "Kabinet sayısı"]
    )
    filters.get_by_label("Koşul 1 işlemi", exact=True).select_option("eq")
    filters.get_by_label("Koşul 1 değeri", exact=True).fill("L-0")
    filters.get_by_role("button", name="Koşul ekle", exact=True).click()
    filters.get_by_label("Koşul 2 alanı", exact=True).select_option("department_name")
    filters.get_by_label("Koşul 2 işlemi", exact=True).select_option("eq")
    filters.get_by_label("Koşul 2 değeri", exact=True).fill("B")
    filters.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(table.get_by_role("button", name="Arşiv Odası", exact=True)).to_be_visible()
    expect(table.get_by_role("row")).to_have_count(2)
    page.get_by_role("button", name="Filtreler (2)", exact=True).click()
    filters = page.get_by_role("dialog").last
    filters.get_by_role("button", name="Temizle", exact=True).click()
    filters.get_by_role("button", name="Koşul ekle", exact=True).click()
    filters.get_by_label("Koşul 1 alanı", exact=True).select_option("institution_name")
    filters.get_by_label("Koşul 1 değeri", exact=True).fill("Fixture")
    filters.get_by_role("button", name="Koşul ekle", exact=True).click()
    filters.get_by_label("Koşul 2 alanı", exact=True).select_option("cabinet_count")
    filters.get_by_label("Koşul 2 işlemi", exact=True).select_option("gt")
    filters.get_by_label("Koşul 2 değeri", exact=True).fill("1")
    filters.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(page.get_by_role("button", name="Sunucu Odası", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Filtreler (2)", exact=True).click()
    filters = page.get_by_role("dialog").last
    filters.get_by_role("button", name="Koşul ekle", exact=True).click()
    filters.get_by_label("Koşul 3 alanı", exact=True).select_option("name")
    filters.get_by_label("Koşul 3 bağlantısı", exact=True).select_option("or")
    filters.get_by_label("Koşul 3 işlemi", exact=True).select_option("eq")
    filters.get_by_label("Koşul 3 değeri", exact=True).fill("Sunucu Odası")
    check("filters")
    filters.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(page.get_by_role("button", name="Sunucu Odası", exact=True)).to_be_visible()
    check("groups")
    page.get_by_role("button", name="Filtreler (3)", exact=True).click()
    filters = page.get_by_role("dialog").last
    filters.get_by_role("button", name="Temizle", exact=True).click()
    filters.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    page.get_by_role("button", name="Sunucu Odası", exact=True).click()
    page.get_by_role("button", name="4", exact=True).click()
    expect(page.get_by_role("dialog").last).to_contain_text("Switch 1")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    form = page.get_by_role("dialog").last
    form.get_by_label("Kabinet no", exact=False).fill("5")
    form.get_by_label("Lokasyon", exact=False).select_option(label="Kuzey Kampüs")
    form.get_by_label("Oda", exact=False).select_option(label="Sunucu Odası")
    check("cabinet-form")
    form.get_by_role("button", name="Kaydı kaydet", exact=False).click()
    expect(page.get_by_role("button", name="5", exact=True)).to_be_visible()
    page.get_by_label("5 kabinetini seç", exact=True).check()
    page.on("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Seçilenleri sil (1)", exact=True).click()
    expect(page.get_by_role("button", name="5", exact=True)).to_have_count(0)
    page.evaluate("location.hash='sites'")
    page.get_by_role("button", name="Kuzey Kampüs", exact=True).click()
    expect(page.get_by_role("columnheader", name="Kat numarası", exact=True)).to_be_visible()
    expect(page.get_by_role("row").filter(has_text="Sunucu Odası")).to_contain_text("L-0")
    page.get_by_role("button", name="Oda ekle", exact=True).click()
    form = page.get_by_role("dialog").last
    form.get_by_label("Oda ismi", exact=False).fill("Test odası")
    form.get_by_label("Kat numarası", exact=False).fill("L-1")
    form.get_by_label("Bölüm adı", exact=False).fill("B")
    check("room-form")
    form.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="Test odası", exact=True)).to_be_visible()
    page.get_by_label("Test odası odasını seç", exact=True).check()
    page.get_by_role("button", name="Seçilen odaları sil (1)", exact=True).click()
    expect(page.get_by_role("cell", name="Test odası", exact=True)).to_have_count(0)
    check("room-list")
    page.evaluate("location.hash='devices'")
    expect(page.get_by_role("columnheader", name="Kabin no", exact=False)).to_be_visible()
    expect(page.get_by_role("cell", name="L-0/A/4/13U", exact=True)).to_be_visible()
    check("inventory")
    assert not errors, errors
    browser.close()
print(
    "PASS: floor groups, natural floor and department order, six-column priority, floor/department search and filters, no root deletion, navigation, desktop/mobile, themes and accessibility"
)
