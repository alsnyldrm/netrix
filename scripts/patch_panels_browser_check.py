"""Create CAT/fiber panels, configure ports, and read the reverse device record."""

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
    page.get_by_role("button", name="K-01", exact=True).click()
    rack = page.get_by_role("dialog").last

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
                page.screenshot(path=f"/tmp/netrix-patch-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    rack.get_by_label("Panel adı", exact=True).fill("CAT-01")
    rack.get_by_label("Port sayısı", exact=True).fill("4")
    rack.get_by_role("button", name="Patch panel ekle", exact=True).click()
    ports = page.get_by_role("dialog").last
    ports.get_by_role("button", name="Port 1 · Boş", exact=True).click()
    ports.get_by_label("Port numarası", exact=True).fill("C-01")
    ports.get_by_label("Bağlı cihaz", exact=True).select_option(label="Switch 1 · 198.51.100.1")
    expect(ports.get_by_label("Bağlı cihaz portu", exact=True)).to_be_enabled()
    expect(ports.get_by_label("Bağlı cihaz portu", exact=True).locator("option")).to_have_count(2)
    assert "B2" not in ports.get_by_label("Bağlı cihaz portu", exact=True).inner_text()
    ports.get_by_label("Bağlı cihaz portu", exact=True).select_option(label="A1")
    ports.get_by_label("Kablo modeli", exact=True).select_option("Cat6")
    ports.get_by_role("button", name="Port bağlantısını kaydet", exact=True).click()
    expect(ports.get_by_role("status")).to_have_text("Port C-01 kaydedildi.")
    check("cat-port")
    ports.get_by_role("button", name="Port 2 · Boş", exact=True).click()
    ports.get_by_label("Cihaz girişi", exact=True).select_option("manual")
    ports.get_by_label("Bağlı cihaz adı / IP", exact=True).fill("External storage")
    ports.get_by_label("Bağlı cihaz portu (manuel)", exact=True).fill("eth1")
    ports.get_by_label("Kablo modeli", exact=True).select_option("Cat7")
    ports.get_by_role("button", name="Port bağlantısını kaydet", exact=True).click()
    expect(ports.get_by_role("status")).to_have_text("Port 2 kaydedildi.")
    ports.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    rack = page.get_by_role("dialog").last
    rack.get_by_label("Panel adı", exact=True).fill("FIBER-01")
    rack.get_by_label("Panel türü", exact=True).select_option("fiber")
    rack.get_by_label("Panel başlangıç U", exact=True).fill("2")
    rack.get_by_label("Port sayısı", exact=True).fill("4")
    rack.get_by_role("button", name="Patch panel ekle", exact=True).click()
    ports = page.get_by_role("dialog").last
    ports.get_by_role("button", name="Port 1 · Boş", exact=True).click()
    options = ports.get_by_label("Kablo modeli", exact=True).locator("option").all_text_contents()
    assert set(options) == {"Seçilmedi", "OM3", "OM4", "Multimode MM", "Singlemode SM"}
    ports.get_by_label("Cihaz girişi", exact=True).select_option("manual")
    ports.get_by_label("Bağlı cihaz adı / IP", exact=True).fill("Switch 2")
    ports.get_by_label("Bağlı cihaz portu (manuel)", exact=True).fill("B2")
    ports.get_by_label("Kablo modeli", exact=True).select_option("OM4")
    ports.get_by_role("button", name="Port bağlantısını kaydet", exact=True).click()
    expect(ports.get_by_role("status")).to_have_text("Port 1 kaydedildi.")
    check("fiber-port")
    ports.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    check("rack")
    page.get_by_role("dialog").last.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.evaluate("location.hash='devices'")
    page.get_by_role("button", name="Switch 1", exact=True).click()
    detail = page.get_by_role("dialog").last
    expect(detail.get_by_role("heading", name="Patch bilgileri", exact=True)).to_be_visible()
    patch_row = detail.get_by_role("row").filter(has=page.get_by_role("cell", name="C-01", exact=True))
    expect(patch_row).to_contain_text("CAT-01")
    expect(patch_row).to_contain_text("A1")
    expect(patch_row).to_contain_text("Cat6")
    check("device")
    assert not errors, errors
    browser.close()
print(
    "PASS: CAT/fiber panel creation, scoped inventory port selector, manual cabling, reverse device info, desktop/mobile, themes and accessibility"
)
