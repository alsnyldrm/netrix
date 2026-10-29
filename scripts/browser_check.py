import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8201")
assert BASE.startswith("http://127.0.0.1:"), "Local disposable test server required"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1512, "height": 1000}, reduced_motion="reduce")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    if page.get_by_text("İlk bağlantıyı kuralım.").count():
        page.get_by_label("Kurulum anahtarı").fill("browser-fixture-setup-token-only")
        page.get_by_label("Ad soyad", exact=True).fill("Tarayıcı Testi")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role(
        "button",
        name="Çalışma alanını oluştur"
        if page.get_by_text("İlk bağlantıyı kuralım.").count()
        else "Çalışma alanına gir",
    ).click()
    expect(page.get_by_role("heading", name="Ağınızın bütün resmi")).to_be_visible()
    page.wait_for_load_state("networkidle")
    Path("artifacts").mkdir(exist_ok=True)
    expect(page.locator(".connection-label")).to_have_text("Bağlı", timeout=10000)
    page.screenshot(path="artifacts/overview-desktop.png", full_page=True)
    # Her grup bağımsız açılır/kapanır; kapalı bağlantılar Tab sırasından çıkar.
    groups = page.locator(".nav-group-title")
    expect(groups).to_have_count(6)
    for heading in groups.all():
        panel = page.locator("#" + heading.get_attribute("aria-controls"))
        heading.click()
        expect(heading).to_have_attribute("aria-expanded", "false")
        expect(panel).not_to_be_visible()
        heading.press("Enter")
        expect(heading).to_have_attribute("aria-expanded", "true")
        expect(panel).to_be_visible()
    inventory = page.get_by_role("button", name="Envanter", exact=True)
    ipam = page.get_by_role("button", name="IP adres yönetimi", exact=True)
    inventory.click()
    inventory.press("Tab")
    expect(ipam).to_be_focused()
    ipam.press("Space")
    expect(ipam).to_have_attribute("aria-expanded", "false")
    expect(inventory).to_have_attribute("aria-expanded", "false")
    ipam.press("Space")
    # Doğrudan gezinme, hedef sayfanın kapalı grubunu açar.
    page.goto(BASE + "/#sites")
    expect(inventory).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_role("button", name="Lokasyonlar", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    page.screenshot(path="artifacts/menu-groups-desktop.png", full_page=True)
    # Use live DOM names discovered from the command palette and navigation.
    page.get_by_role("button", name="Cihaz envanteri", exact=True).click()
    expect(page.get_by_role("heading", name="Cihaz envanteri", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Cihaz envanteri", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    # Text selection may end over the backdrop; it must not discard the form.
    for label, value in [
        ("Cihaz adı", "iputils-ping"),
        ("Üretici", "Fixture vendor"),
        ("Model", "Fixture model"),
    ]:
        field = page.get_by_label(label)
        field.fill(value)
        field.dblclick()
        expect(page.get_by_role("dialog")).to_be_visible()
        field_box = field.bounding_box()
        dialog_box = page.get_by_role("dialog").bounding_box()
        y = field_box["y"] + field_box["height"] / 2
        page.mouse.move(field_box["x"] + field_box["width"] - 8, y)
        page.mouse.down()
        page.mouse.move(dialog_box["x"] - 8, y, steps=12)
        page.mouse.up()
        expect(page.get_by_role("dialog")).to_be_visible()
        expect(field).to_have_value(value)
        assert field.evaluate("e => e.selectionEnd > e.selectionStart"), label
    expect(page.get_by_label("Cihaz adı")).to_have_value("iputils-ping")
    expect(page.get_by_label("Üretici", exact=True)).to_have_value("Fixture vendor")
    expect(page.get_by_label("Model", exact=True)).to_have_value("Fixture model")
    # A click after selecting text must not dismiss and erase the draft either.
    page.mouse.click(dialog_box["x"] - 8, dialog_box["y"] + 40)
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.get_by_label("Cihaz adı")).to_have_value("iputils-ping")
    page.get_by_label("Model", exact=True).fill("")
    fixture_name = "Browser fixture " + uuid4().hex[:8]
    fixture_ip = "2001:db8::" + uuid4().hex[:4] + ":" + uuid4().hex[:4]
    page.get_by_label("Cihaz adı").fill(fixture_name)
    page.get_by_label("Yönetim IP adresi").fill(fixture_ip)
    page.get_by_role("combobox", name="VRF *", exact=True).select_option(label="Global")
    page.get_by_role("button", name="Kaydı kaydet").click()
    expect(page.get_by_role("button", name=fixture_name + " Model belirtilmedi")).to_be_visible()
    page.get_by_role("button", name=fixture_name + " ayrıntıları").click()
    expect(page.get_by_role("heading", name=fixture_name, exact=True)).to_be_visible()
    page.get_by_role("button", name="Pencereyi kapat").click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    page.get_by_label("Cihaz adı").fill("Cancelled draft")
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("button", name="Yeni kayıt", exact=True)).to_be_focused()
    # Keyboard dialog behavior, navigation, and empty states across every page.
    keys = [
        "interfaces",
        "sites",
        "prefixes",
        "addresses",
        "vlans",
        "vrfs",
        "discovery",
        "topology",
        "jobs",
        "events",
        "configuration",
        "monitoring",
        "alerts",
        "rules",
        "credentials",
        "audit",
        "users",
        "settings",
    ]
    for key in keys:
        page.goto(BASE + "/#" + key)
        page.wait_for_load_state("networkidle")
        expect(page.locator("main h1")).to_be_visible()
        assert page.locator("body").evaluate("(e)=>e.scrollWidth<=window.innerWidth"), key
    page.goto(BASE + "/#overview")
    page.keyboard.press("Control+k")
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_label("Sayfa veya cihaz ara").fill("Ağ keşfi")
    page.get_by_role("button", name="Ağ keşfi Keşif & bağlantı").click()
    expect(page.get_by_role("heading", name="Ağ keşfi", exact=True)).to_be_visible()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    # No page-wide horizontal overflow at supported widths.
    for width, height in [(375, 812), (812, 375), (768, 1024), (1440, 900)]:
        page.set_viewport_size({"width": width, "height": height})
        for key in ("overview", "devices", "discovery", "monitoring", "settings"):
            page.goto(BASE + "/#" + key)
            page.wait_for_load_state("networkidle")
            assert page.locator("body").evaluate("(e)=>e.scrollWidth<=window.innerWidth"), (width, key)
        if width == 375:
            page.goto(BASE + "/#overview")
            page.wait_for_load_state("networkidle")
            page.screenshot(path="artifacts/overview-mobile.png", full_page=True)
            # Mobil çekmece menü: açılır, sayfaya gider ve kapanır.
            expect(page.get_by_role("button", name="Ağ blokları", exact=True)).not_to_be_visible()
            page.get_by_role("button", name="Menüyü aç").click()
            ipam.click()
            expect(page.get_by_role("button", name="Ağ blokları", exact=True)).not_to_be_visible()
            page.screenshot(path="artifacts/menu-groups-mobile.png", full_page=True)
            ipam.click()
            page.get_by_role("button", name="Ağ blokları", exact=True).click()
            expect(page.get_by_role("heading", name="Ağ blokları", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="Ağ blokları", exact=True)).not_to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})
    # Tema anahtarı açık ve koyu tema arasında geçer.
    start = page.evaluate("document.documentElement.dataset.theme")
    page.locator(".topbar .theme-toggle").click()
    assert page.evaluate("document.documentElement.dataset.theme") != start
    page.locator(".topbar .theme-toggle").click()
    assert page.evaluate("document.documentElement.dataset.theme") == start
    # Daraltılmış sidebar ikonlarla gezinmeye devam eder.
    page.get_by_role("button", name="Operasyon", exact=True).click()
    expect(page.get_by_role("button", name="Trafik gözlemevi", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="Menüyü daralt").click()
    page.get_by_role("button", name="Trafik gözlemevi", exact=True).click()
    expect(page.get_by_role("heading", name="Trafik gözlemevi", exact=True)).to_be_visible()
    page.get_by_role("button", name="Menüyü genişlet").click()
    page.get_by_role("button", name="Güvenli çıkış").click()
    expect(page.get_by_role("heading", name="Tekrar hoş geldiniz.")).to_be_visible()
    assert not errors, errors
    print(
        json.dumps(
            {
                "pages": len(keys) + 2,
                "viewports": 4,
                "flows": [
                    "setup/login",
                    "create device",
                    "device detail",
                    "command palette",
                    "escape dialog",
                    "mobile overflow",
                    "mobile drawer",
                    "theme toggle",
                    "collapsed sidebar",
                    "independent menu groups",
                    "keyboard group toggles and tab order",
                    "navigation reveals closed group",
                    "mobile group toggles",
                    "text selection ending outside dialog preserves form",
                    "backdrop click preserves draft and explicit cancel closes",
                ],
                "console_errors": errors,
            }
        )
    )
    browser.close()
