"""End-to-end against scripts/inventory_fixture.py; local database only."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8205"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    modal_reports = {}

    def check_modal(name):
        Path("artifacts").mkdir(exist_ok=True)
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            dialog = page.get_by_role("dialog")
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
            if width == 1440:
                for selector in (".filter-rule", ".bulk-field"):
                    for row in dialog.locator(selector).all():
                        boxes = row.locator("select, input:not([type=checkbox])").evaluate_all(
                            "els=>els.map(e=>{const r=e.getBoundingClientRect();return {y:r.y,h:r.height};})"
                        )
                        if len(boxes) > 1:
                            assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) <= 1, (name, boxes)
                            assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) <= 1, (name, boxes)
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            report = page.evaluate(
                "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
            )
            modal_reports[f"{name}-{width}"] = [v["id"] for v in report["violations"]]
            if name == "interfaces":
                dialog.locator(".interface-picker").scroll_into_view_if_needed()
            page.screenshot(path=f"artifacts/inventory-modal-{name}-{width}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
    expect(search).to_be_visible()
    expect(page.locator(".inventory-pagination")).to_contain_text("35 kayıt")
    search.fill("Kuzey")
    expect(page.locator(".inventory-pagination")).to_contain_text("35 kayıt")
    search.fill("Firewall")
    expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    page.get_by_role("button", name="Sütunlar", exact=True).click()
    page.get_by_role("checkbox", name="Adaptör", exact=True).check()
    check_modal("columns")
    page.get_by_role("button", name="Sütunları uygula", exact=True).click()
    expect(page.get_by_role("columnheader", name="Adaptör", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name="Fixture 00 seç", exact=True).check()
    page.get_by_role("button", name="Toplu değiştir", exact=True).click()
    expect(page.get_by_role("checkbox", name="Cihaz adı değiştir", exact=True)).to_have_count(0)
    page.get_by_role("checkbox", name="Üretici değiştir", exact=True).check()
    page.get_by_role("textbox", name="Üretici değeri", exact=True).fill("Updated vendor")
    check_modal("bulk")
    page.get_by_role("button", name="Seçilenlere uygula", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("cell", name="Updated vendor", exact=True)).to_be_visible()
    page.get_by_role("button", name="Fixture 00 ayrıntıları", exact=True).click()
    expect(page.get_by_role("checkbox", name="port1 uygulamaya ekle", exact=True)).to_be_checked()
    page.get_by_role("checkbox", name="port2 uygulamaya ekle", exact=True).check()
    check_modal("interfaces")
    page.get_by_role("button", name="Arayüz seçimini kaydet", exact=True).click()
    expect(page.get_by_text("Arayüz seçimi kaydedildi.", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    page.goto(BASE + "/#interfaces")
    search.fill("Firewall")
    page.get_by_role("button", name="Fixture 00 arayüzleri", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    expect(page.get_by_role("columnheader", name="Cihaz türü", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name="port2 seç", exact=True).check()
    page.get_by_role("button", name="Devre dışı bırak", exact=True).click()
    expect(
        page.get_by_role("row").filter(has=page.get_by_role("cell", name="port2", exact=True))
    ).to_contain_text("Kapalı")
    # A real server-side AND/OR filter, with no table-page-only filtering.
    page.get_by_role("button", name="Filtreler", exact=True).click()
    page.get_by_role("button", name="Koşul ekle", exact=True).click()
    page.get_by_label("Koşul 1 alanı", exact=True).select_option("if_index")
    page.get_by_label("Koşul 1 işlemi", exact=True).select_option("eq")
    page.get_by_label("Koşul 1 değeri", exact=True).fill("2")
    check_modal("filters")
    page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    page.goto(BASE + "/#configuration")
    expect(page.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    page.get_by_role("button", name="Görüntüle", exact=True).first.click()
    expect(page.locator(".backup-result pre")).to_contain_text("hostname")
    assert "FIXTURE-SECRET" not in page.locator(".backup-result").inner_text()
    page.keyboard.press("Escape")
    page.goto(BASE + "/#backup-changes")
    expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    page.goto(BASE + "/#backup-compare")
    page.get_by_role("button", name="Aktif config ile karşılaştır", exact=True).first.click()
    expect(page.get_by_role("dialog")).to_contain_text(
        "kapsamında"
    )  # no authorized device scope: no network calls
    page.keyboard.press("Escape")
    page.goto(BASE + "/#backup-settings")
    search.fill("Firewall")
    page.get_by_role("checkbox", name="Fixture 00 seç", exact=True).check()
    page.get_by_role("button", name="Ayarları uygula", exact=True).click()
    expect(page.get_by_role("checkbox", name="Yedek grubu değiştir", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    page.goto(BASE + "/#backup-groups")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    page.get_by_label("Grup adı", exact=False).fill("Backbone")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="Backbone", exact=True)).to_be_visible()
    reports = {}
    Path("artifacts").mkdir(exist_ok=True)
    for key in (
        "devices",
        "interfaces",
        "configuration",
        "backup-changes",
        "backup-compare",
        "backup-settings",
        "backup-groups",
    ):
        for theme, width, height in (("light", 1440, 1000), ("dark", 375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(BASE + "/#" + key)
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            page.wait_for_timeout(300)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), key
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            report = page.evaluate(
                "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
            )
            reports[f"{key}-{theme}"] = [v["id"] for v in report["violations"]]
            page.screenshot(path=f"artifacts/inventory-{key}-{theme}.png", full_page=True)
    assert not any(reports.values()), reports
    assert not any(modal_reports.values()), modal_reports
    assert not errors, errors
    print(
        json.dumps(
            {
                "inventory_backup_workflows": "PASS",
                "screens": 7,
                "axe": reports,
                "dialogs": modal_reports,
                "console_errors": errors,
            }
        )
    )
    browser.close()
