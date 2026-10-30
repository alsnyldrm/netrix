"""Delete confirmation and durable exclusion on the disposable rescan fixture."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8224")
assert base.startswith("http://127.0.0.1:"), "Only a local disposable fixture may be mutated"
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/#topology")
    page.get_by_label("E-posta").fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    directory = page.get_by_role("region", name="Bağlantı cihazları")
    directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
    table = page.get_by_role("region", name="Bağlantı kayıtları")
    row = table.get_by_role("row").filter(has=page.get_by_role("cell", name="Edge-01", exact=True))
    remove = row.get_by_role("button", name="1 komşuluğunu sil", exact=True)
    remove.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Komşuluk kaydını sil")
    expect(dialog).to_contain_text("sonraki taramalarda yeniden eklenmesi engellenecek")
    page.keyboard.press("Escape")
    expect(remove).to_be_focused()
    expect(table.locator(".inventory-pagination")).to_contain_text("4 kayıt")
    remove.click()
    for width, height in [(1440, 1000), (375, 812), (812, 375)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ["light", "dark"]:
            page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
            boxes = dialog.locator("dd").evaluate_all("els=>els.map(e=>e.getBoundingClientRect().x)")
            assert max(boxes) - min(boxes) < 1
            assert all(
                b.bounding_box()["height"] >= 44 for b in dialog.locator(".dialog-footer button").all()
            )
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            issues = page.evaluate(
                "async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            assert not issues, (width, theme, issues)
            page.screenshot(path=f"artifacts/link-delete-{width}-{theme}.png")
    page.route(
        "**/api/v1/links/*",
        lambda route: (
            route.fulfill(status=409, json={"detail": "Test: kayıt güncellendi"})
            if route.request.method == "DELETE"
            else route.continue_()
        ),
    )
    dialog.get_by_role("button", name="Sil ve engelle", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Test: kayıt güncellendi")
    page.unroute("**/api/v1/links/*")
    dialog.get_by_role("button", name="Sil ve engelle", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(table.locator(".inventory-pagination")).to_contain_text("3 kayıt")
    expect(row).to_have_count(0)
    for _ in range(2):
        response = page.request.post(base + "/__fixture__/rescan", headers={"X-Netrix-Request": "1"})
        assert response.ok, response.text()
        page.reload()
        directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
        expect(table.locator(".inventory-pagination")).to_contain_text("3 kayıt")
        expect(row).to_have_count(0)
    assert not errors, errors
    print(
        "PASS: cancel, retry, delete, two subsequent scans, persisted absence, desktop/mobile/landscape alignment, axe"
    )
    browser.close()
