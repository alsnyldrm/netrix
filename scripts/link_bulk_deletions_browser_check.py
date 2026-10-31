"""Selection and atomic bulk deletion on the disposable rescan fixture."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8227")
assert base.startswith("http://127.0.0.1:"), "Only a local disposable fixture may be mutated"
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
    table = page.get_by_role("region", name="Bağlantı kayıtları")
    expect(table.locator(".inventory-pagination")).to_contain_text("4 kayıt")
    remove = table.get_by_role("button", name="Sil", exact=True)
    all_rows = table.get_by_role("checkbox", name="Bu sayfadaki kayıtları seç", exact=True)
    expect(remove).to_have_count(0)
    all_rows.check()
    expect(table.locator(".inventory-selection")).to_contain_text("4 kayıt seçildi")
    assert table.locator("tbody input:checked").count() == 4
    table.locator("tbody input").first.uncheck()
    assert all_rows.evaluate("e => e.indeterminate")
    table.get_by_role("button", name="Seçimi kaldır", exact=True).click()
    expect(remove).to_have_count(0)
    all_rows.check()
    table.get_by_role("button", name="Komşu: artan sırala", exact=True).click()
    expect(remove).to_have_count(0)
    expect(table.get_by_text("Kayıtlar yükleniyor…", exact=True)).to_have_count(0)
    for name in ("Controller", "Edge-01"):
        checkbox = table.get_by_role("checkbox", name=f"1 · {name} komşuluğunu seç", exact=True)
        checkbox.focus()
        checkbox.press("Space")
    expect(table.locator(".inventory-selection")).to_contain_text("2 kayıt seçildi")
    expect(table.get_by_role("button", name="Etkinleştir", exact=True)).to_have_count(0)

    def inspect(name, modal=False):
        for width, height in [(1440, 1000), (375, 812), (812, 375)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                if modal:
                    assert page.get_by_role("dialog").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                else:
                    boxes = table.locator(".neighbor-selection-control").evaluate_all(
                        "els => els.map(e => {const r=e.getBoundingClientRect();return {x:r.x,w:r.width,h:r.height};})"
                    )
                    assert all(b["w"] >= 44 and b["h"] >= 44 for b in boxes)
                    assert table.locator(".neighbor-selection-control").evaluate_all(
                        "els => els.every(e => {const a=e.getBoundingClientRect(), b=e.querySelector('input').getBoundingClientRect();return Math.abs(a.y+a.height/2-b.y-b.height/2)<1;})"
                    )
                    assert max(b["x"] for b in boxes) - min(b["x"] for b in boxes) <= 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                issues = page.evaluate(
                    "async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                assert not issues, (width, theme, issues)
                (page.get_by_role("dialog") if modal else table).screenshot(
                    path=f"artifacts/bulk-delete-{name}-{width}-{theme}.png"
                )
        page.set_viewport_size({"width": 1440, "height": 1000})

    inspect("selection")
    remove.click()
    dialog = page.get_by_role("dialog", name="Seçilen komşulukları sil")
    expect(dialog).to_contain_text("2 komşuluk kaydı silinecek")
    page.keyboard.press("Escape")
    expect(remove).to_be_focused()
    expect(table.locator(".inventory-selection")).to_contain_text("2 kayıt seçildi")
    remove.click()
    inspect("confirmation", modal=True)
    page.route(
        "**/api/v1/inventory/links/bulk",
        lambda route: route.fulfill(status=409, json={"detail": "Test: seçim güncellendi"}),
    )
    dialog.get_by_role("button", name="Seçilenleri sil ve engelle", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Test: seçim güncellendi")
    page.unroute("**/api/v1/inventory/links/bulk")
    with page.expect_response(lambda r: "/inventory/links/bulk" in r.url) as pending:
        dialog.get_by_role("button", name="Seçilenleri sil ve engelle", exact=True).click()
    assert pending.value.ok and pending.value.json() == {"updated": 2}
    expect(dialog).to_have_count(0)
    expect(table.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    expect(remove).to_have_count(0)
    expect(table.get_by_role("status")).to_contain_text("2 komşuluk kaydı silindi")
    for _ in range(2):
        response = page.request.post(base + "/__fixture__/rescan", headers={"X-Netrix-Request": "1"})
        assert response.ok
        page.reload()
        directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
        expect(table.locator(".inventory-pagination")).to_contain_text("2 kayıt")
        for name in ("Controller", "Edge-01"):
            expect(table.get_by_role("cell", name=name, exact=True)).to_have_count(0)
    assert not errors, errors
    print(
        "PASS: selection, select all, indeterminate, keyboard, sort reset, cancel/retry, bulk delete, two rescans, desktop/mobile alignment and axe"
    )
    browser.close()
