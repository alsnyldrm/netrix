"""Edit and restore neighbor labels against a disposable topology fixture."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8221")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
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
    edit = row.get_by_role("button", name="1 komşuluğunu düzenle", exact=True)
    edit.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Komşuluk kaydını düzenle")
    expect(dialog.get_by_label("Komşu", exact=True)).to_have_value("Edge-01")
    expect(dialog.get_by_label("Uzak port", exact=True)).to_have_value("2")
    dialog.get_by_label("Komşu", exact=True).fill("discarded")
    page.keyboard.press("Escape")
    expect(edit).to_be_focused()
    edit.click()
    dialog.get_by_label("Komşu", exact=True).fill("Edge-02")
    dialog.get_by_label("Uzak port", exact=True).fill("Gi1/0/49")
    for width, height in [(1440, 1000), (375, 812), (812, 375)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ["light", "dark"]:
            page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            boxes = dialog.locator("input").evaluate_all(
                "els => els.map(e => {const r=e.getBoundingClientRect();return {x:r.x,w:r.width,h:r.height};})"
            )
            assert abs(boxes[0]["x"] - boxes[1]["x"]) < 1
            assert abs(boxes[0]["w"] - boxes[1]["w"]) < 1
            assert all(b["h"] >= 44 for b in boxes)
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            issues = page.evaluate(
                "async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            assert not issues, (width, theme, issues)
            page.screenshot(path=f"artifacts/link-label-form-{width}-{theme}.png", full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    # Failure leaves edits available for retry.
    page.route(
        "**/api/v1/links/*/labels",
        lambda route: route.fulfill(status=409, json={"detail": "Test kayıt yenilendi"}),
    )
    dialog.get_by_role("button", name="Kaydet", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Test kayıt yenilendi")
    expect(dialog.get_by_label("Komşu", exact=True)).to_have_value("Edge-02")
    page.unroute("**/api/v1/links/*/labels")
    dialog.get_by_role("button", name="Kaydet", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text="Komşuluk kaydı güncellendi")).to_be_visible()
    expect(table.get_by_role("cell", name="Gi1/0/49 Düzenlendi", exact=True)).to_be_visible()
    expect(table.get_by_text("Düzenlendi", exact=True)).to_have_count(2)
    page.reload()
    directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
    expect(table.get_by_role("cell", name="Gi1/0/49 Düzenlendi", exact=True)).to_be_visible()
    edited = table.get_by_role("row").filter(has=page.get_by_role("cell", name="Gi1/0/49 Düzenlendi", exact=True))
    edited.get_by_role("button", name="1 komşuluğunu düzenle", exact=True).click()
    dialog.locator("summary").click()
    expect(dialog.locator("dd").first).to_have_text("Edge-01")
    expect(dialog.locator("dd").nth(1)).to_have_text("2")
    dialog.get_by_role("button", name="Keşif değerlerini kullan", exact=True).click()
    expect(table.get_by_role("cell", name="Edge-01", exact=True)).to_be_visible()
    expect(table.get_by_text("Düzenlendi", exact=True)).to_have_count(0)
    assert not errors, errors
    print(
        json.dumps(
            {
                "neighbor_edit": "PASS",
                "cancel_retry_restore_persistence": "PASS",
                "axe": "PASS",
                "sizes": [1440, 375, 812],
                "errors": errors,
            }
        )
    )
    browser.close()
