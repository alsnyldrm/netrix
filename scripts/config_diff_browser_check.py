"""Real saved-diff API in disposable local fixture; no device connections."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto("http://127.0.0.1:8205/#backup-changes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_role("button", name="Fark", exact=True)).to_have_count(2)
    Path("artifacts").mkdir(exist_ok=True)
    for width, theme in ((1440, "light"), (375, "dark")):
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        page.get_by_role("button", name="Fark", exact=True).first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.locator("pre")).to_contain_text("Yalnızca dosya üstbilgisi değişmiş")
        expect(dialog.locator("pre")).not_to_contain_text("config system global")
        expect(dialog).to_contain_text("Önceki yedek:")
        expect(dialog).to_contain_text("iki kayıtlı yedek arasındadır")
        page.screenshot(path=f"artifacts/config-header-diff-{width}.png", full_page=True)
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Fark", exact=True).nth(1).click()
        expect(dialog.locator("pre")).to_contain_text("Bölüm: config system global")
        expect(dialog.locator("pre")).to_contain_text("-    set admintimeout 5")
        expect(dialog.locator("pre")).to_contain_text("+    set admintimeout 15")
        expect(dialog.locator("pre")).to_contain_text('config system admin > edit "admin"')
        expect(dialog.locator("pre")).to_contain_text("set password [REDACTED SECRET]")
        assert "PRIVATE" not in dialog.locator("pre").inner_text()
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        edges = dialog.locator(".backup-result > p, .backup-result > pre").evaluate_all(
            "els=>els.map(e=>e.getBoundingClientRect().left)"
        )
        assert max(edges) - min(edges) < 1
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[theme] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
        )
        page.screenshot(path=f"artifacts/config-setting-diff-{width}.png", full_page=True)
        page.keyboard.press("Escape")
    assert not errors and not any(reports.values()), (errors, reports)
    print(json.dumps({"diff_sections": "PASS", "axe": reports, "errors": errors}))
    browser.close()
