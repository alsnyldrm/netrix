"""Round-trip deleted neighbors through the menu on the disposable rescan fixture."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8229")
assert base.startswith("http://127.0.0.1:"), "Only a disposable local fixture may be mutated"
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/#neighbors")
    page.get_by_label("E-posta").fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    directory = page.get_by_role("region", name="Bağlantı cihazları")
    directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
    active = page.get_by_role("region", name="Bağlantı kayıtları")
    expect(active.locator(".inventory-pagination")).to_contain_text("4 kayıt")
    for name in ("Controller", "Edge-01"):
        active.get_by_role("checkbox", name=f"1 · {name} komşuluğunu seç", exact=True).check()
    active.get_by_role("button", name="Sil", exact=True).click()
    page.get_by_role("button", name="Seçilenleri sil ve engelle", exact=True).click()
    expect(active.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    if not page.get_by_role("button", name="Silinen komşuluklar", exact=True).is_visible():
        page.get_by_role("button", name="Keşif & bağlantı", exact=True).click()
    page.get_by_role("button", name="Silinen komşuluklar", exact=True).click()
    table = page.get_by_role("region", name="Silinen komşuluk kayıtları")
    expect(table.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    table.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Edge")
    expect(table.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    table.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("")
    expect(table.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    table.get_by_role("button", name="Filtreler", exact=True).click()
    for i, (field, op, value, join) in enumerate(
        [
            ("remote_name", "contains", "Edge", "and"),
            ("remote_name", "contains", "Controller", "or"),
            ("remote_name", "not_contains", "Controller", "and"),
        ],
        1,
    ):
        page.get_by_role("button", name="Koşul ekle", exact=True).click()
        page.get_by_label(f"Koşul {i} alanı", exact=True).select_option(field)
        page.get_by_label(f"Koşul {i} işlemi", exact=True).select_option(op)
        page.get_by_label(f"Koşul {i} değeri", exact=True).fill(value)
        if i > 1:
            page.get_by_label(f"Koşul {i} bağlantısı", exact=True).select_option(join)
    page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(table.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    table.get_by_role("button", name="Sütunlar", exact=True).click()
    page.get_by_role("checkbox", name="Kaynak IP", exact=True).check()
    page.get_by_role("button", name="Sütunları uygula", exact=True).click()
    table.get_by_role("button", name="Komşu: artan sırala", exact=True).click()
    expect(table.get_by_role("columnheader", name="Komşu", exact=True)).to_have_attribute(
        "aria-sort", "ascending"
    )
    expect(table.get_by_text("Kayıtlar yükleniyor…", exact=True)).to_have_count(0)

    def inspect(name, modal=False):
        for width, height in [(1440, 1000), (375, 812), (812, 375)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                area = page.get_by_role("dialog") if modal else table
                if modal:
                    assert area.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
                buttons = area.locator(".dialog-footer button" if modal else ".inventory-actions .secondary")
                assert all(b.bounding_box()["height"] >= 44 for b in buttons.all())
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                issues = page.evaluate(
                    "async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                assert not issues, (width, theme, issues)
                area.screenshot(path=f"artifacts/restore-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    inspect("list")
    single = table.get_by_role("button", name="1 · Edge-01 komşuluğunu geri yükle", exact=True)
    single.focus()
    single.press("Enter")
    dialog = page.get_by_role("dialog", name="Komşulukları geri yükle")
    expect(dialog).to_contain_text("1 komşuluk kaydı")
    page.keyboard.press("Escape")
    expect(single).to_be_focused()
    single.click()
    inspect("dialog", modal=True)
    page.route(
        "**/api/v1/inventory/links/bulk",
        lambda route: route.fulfill(status=409, json={"detail": "Test: kayıt değişti"}),
    )
    dialog.get_by_role("button", name="Geri yükle", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Test: kayıt değişti")
    page.unroute("**/api/v1/inventory/links/bulk")
    dialog.get_by_role("button", name="Geri yükle", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(table.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    page.reload()
    expect(table.get_by_role("columnheader", name="Kaynak IP", exact=True)).to_be_visible()
    expect(table.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    table.get_by_role("checkbox", name="Bu sayfadaki kayıtları seç", exact=True).check()
    table.locator(".inventory-selection").get_by_role("button", name="Geri yükle", exact=True).click()
    dialog.get_by_role("button", name="Geri yükle", exact=True).click()
    expect(table.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    for _ in range(2):
        assert page.request.post(base + "/__fixture__/rescan", headers={"X-Netrix-Request": "1"}).ok
        page.goto(base + "/#neighbors")
        directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
        expect(active.locator(".inventory-pagination")).to_contain_text("4 kayıt")
        for name in ("Controller", "Edge-01"):
            expect(active.get_by_role("cell", name=name, exact=True)).to_be_visible()
        page.goto(base + "/#deleted-links")
        expect(table.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    assert not errors, errors
    print(
        "PASS: menu, search, AND/OR/not-contains filters, columns, sort, single/bulk restore, cancel/retry, two rescans, desktop/mobile/landscape themes and axe"
    )
    browser.close()
