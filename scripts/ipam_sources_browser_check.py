"""Verify physical labels and firewall form on desktop and mobile."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8215/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    for address, port in [("192.0.2.57", "H1"), ("192.0.2.58", "H3")]:
        row = page.get_by_role("row").filter(has=page.get_by_role("button", name=address, exact=True))
        expect(row).to_contain_text("HP-SW-BB-01-A-00-01")
        expect(row).to_contain_text(port)
        expect(row).not_to_contain_text("IPAM ·")
        expect(row).not_to_contain_text("192.0.2.200")

    def check(name):
        for width, height in [(1440, 1000), (375, 812)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(100)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            for dialog in page.get_by_role("dialog").all():
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id)"
            )
            assert not violations, violations
            page.screenshot(path=f"/tmp/netrix-sources-{name}-{width}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True).click()
    expect(page.get_by_role("row")).to_have_count(4)
    check("addresses")
    page.goto("http://127.0.0.1:8215/#integrations")
    page.get_by_role("button", name="Entegrasyon ekle", exact=True).click()
    page.get_by_label("Entegrasyon türü", exact=False).select_option("firewall")
    page.get_by_label("Entegrasyon adı", exact=True).fill("Firewall fixture")
    page.get_by_label("Sunucu adı veya IP", exact=True).fill("192.0.2.1")
    expect(page.get_by_label("Bağlantı portu", exact=True)).to_have_value("161")
    page.get_by_label("SNMP erişim profili", exact=False).select_option(label="Fixture SNMP")
    assert page.get_by_label("Kullanıcı", exact=True).count() == 0
    check("firewall")
    page.get_by_role("button", name="Entegrasyonu kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("row").filter(has_text="Firewall fixture")).to_contain_text("Firewall")
    assert not errors, errors
    browser.close()
print(
    "PASS: clean switch labels, paired ports, firewall profile/save, desktop/mobile layout and accessibility"
)
