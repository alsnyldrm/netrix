"""Shared not-contains controls across inventory views; disposable topology fixture."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8219")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(base)
    page.get_by_label("E-posta").fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    for route, drill in [
        ("devices", None),
        ("interfaces", None),
        ("interfaces", "HP-SW-BB-01-A-00-01"),
        ("configuration", None),
        ("configuration", "Fixture 00"),
        ("backup-settings", None),
        ("backup-changes", None),
        ("backup-compare", "Fixture 00"),
    ]:
        page.goto(base + "/#" + route)
        if drill:
            page.get_by_role("button", name=drill, exact=True).click()
        page.get_by_role("button", name="Filtreler", exact=True).click()
        page.get_by_role("button", name="Koşul ekle", exact=True).click()
        page.get_by_label("Koşul 1 işlemi", exact=True).select_option(label="İçermez")
        page.get_by_label("Koşul 1 değeri", exact=True).fill("nonexistent-fixture-value")
        for width in (1440, 375):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
            dialog = page.get_by_role("dialog")
            assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            if width == 1440:
                boxes = dialog.locator(".filter-rule select,.filter-rule input").evaluate_all(
                    "els => els.map(e => {const r=e.getBoundingClientRect(); return {y:r.y,h:r.height};})"
                )
                assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) <= 1
                assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) <= 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate(
                "async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/filter-{route}-{bool(drill)}-{width}.png", full_page=True)
        page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
        expect(page.get_by_role("button", name="Filtreler (1)", exact=True)).to_be_visible()
        expect(page.locator(".inventory-panel [role=alert]")).to_have_count(0)
        page.set_viewport_size({"width": 1440, "height": 1000})
    print("PASS: shared not-contains in 8 filter views, desktop/mobile alignment and axe")
    browser.close()
