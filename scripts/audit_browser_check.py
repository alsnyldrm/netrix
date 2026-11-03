"""Audit table and field comparison, against local fixture API only."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8242"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#audit")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.on(
        "request",
        lambda request: (
            writes.append(request.url) if request.method in ("POST", "PUT", "DELETE", "PATCH") else None
        ),
    )
    table = page.locator(".audit-panel")
    expect(table).to_contain_text("Ayşe Yönetici")
    expect(table).to_contain_text("Mehmet Operatör")
    expect(table).not_to_contain_text("ipam_ping")
    expect(table.get_by_role("columnheader", name="Etkilenen kayıt")).to_be_visible()
    search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
    search.fill("Yeni kampüs")
    expect(table.locator("tbody tr")).to_have_count(1)
    expect(table).to_contain_text("Kampüs 26 → Yeni kampüs")
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            page.evaluate("""async () => await Promise.all(document.getAnimations()
                .filter(a => a.effect?.getTiming().iterations !== Infinity)
                .map(a => a.finished.catch(() => {})))""")
            page.evaluate("window.scrollTo(0,0)")
            assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
            # Header and cell left edges must share the same column axes.
            alignment = table.evaluate("""panel => {
              const head = [...panel.querySelectorAll('thead th')].map(e => e.getBoundingClientRect().left);
              return [...panel.querySelectorAll('tbody tr:first-child td')].every((e,i) =>
                Math.abs(e.getBoundingClientRect().left - head[i]) < 1);
            }""")
            assert alignment
            page.screenshot(path=f"/tmp/netrix-audit-table-{width}-{theme}.png", full_page=True)
            table.get_by_role("button", name="Kayıt ayrıntıları", exact=True).click()
            dialog = page.get_by_role("dialog")
            page.evaluate("""async () => await Promise.all(document.getAnimations()
                .filter(a => a.effect?.getTiming().iterations !== Infinity)
                .map(a => a.finished.catch(() => {})))""")
            expect(dialog).to_contain_text("Mehmet Operatör")
            expect(dialog.get_by_role("row")).to_have_count(2)
            expect(dialog.get_by_role("cell", name="Kampüs 26", exact=True)).to_be_visible()
            expect(dialog.get_by_role("cell", name="Yeni kampüs", exact=True)).to_be_visible()
            assert dialog.evaluate("el => el.getBoundingClientRect().right <= innerWidth")
            assert dialog.locator(".audit-changes").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            for view in ("detail",):
                page.screenshot(path=f"/tmp/netrix-audit-{view}-{width}-{theme}.png", full_page=True)
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate("""async () => (await axe.run(document, {
              runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa']}
            })).violations.map(v => ({id:v.id, targets:v.nodes.map(n => n.target)}))""")
            assert not violations, violations
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(table.get_by_role("button", name="Kayıt ayrıntıları", exact=True)).to_be_focused()
            violations = page.evaluate("""async () => (await axe.run(document, {
              runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa']}
            })).violations.map(v => ({id:v.id, targets:v.nodes.map(n => n.target)}))""")
            assert not violations, violations
    search.fill("Geçmiş kayıt")
    expect(table.locator("tbody tr")).to_have_count(1)
    table.get_by_role("button", name="Kayıt ayrıntıları", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("alan bazında önceki ve sonraki değer kaydedilmemiş")
    page.keyboard.press("Escape")
    search.fill("no-match")
    expect(page.get_by_text("Aramanızla eşleşen kayıt yok.", exact=True)).to_be_visible()
    assert not errors, errors
    assert not writes, writes
    print(
        json.dumps(
            {
                "result": "PASS",
                "viewports": [1440, 375],
                "themes": ["dark", "light"],
                "axe_violations": 0,
                "writes_after_login": 0,
                "console_errors": 0,
            }
        )
    )
    browser.close()
