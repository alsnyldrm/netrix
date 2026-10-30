"""Topology table filters, columns and accessible layouts on the local fixture."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8218")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
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
    table = page.get_by_role("region", name="Bağlantı kayıtları")
    expect(table.locator(".inventory-pagination")).to_contain_text("5 kayıt")
    table.get_by_role("button", name="Filtreler", exact=True).click()
    for i, (field, value, join) in enumerate(
        [
            ("device_name", "HP-SW-BB-01-A-00-01", "and"),
            ("device_name", "Edge-01", "or"),
            ("remote_name", "Edge-02", "and"),
        ],
        1,
    ):
        page.get_by_role("button", name="Koşul ekle", exact=True).click()
        page.get_by_label(f"Koşul {i} alanı", exact=True).select_option(field)
        page.get_by_label(f"Koşul {i} işlemi", exact=True).select_option("eq")
        page.get_by_label(f"Koşul {i} değeri", exact=True).fill(value)
        if i > 1:
            page.get_by_label(f"Koşul {i} bağlantısı", exact=True).select_option(join)

    def inspect_view(name, modal=False):
        for width, height in [(1440, 1000), (375, 812), (812, 375)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ["light", "dark"]:
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                if modal:
                    dialog = page.get_by_role("dialog")
                    assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                    if width == 1440:
                        for row in dialog.locator(".filter-rule").all():
                            boxes = row.locator("select,input").evaluate_all(
                                "els => els.map(e => { const r=e.getBoundingClientRect();return {y:r.y,h:r.height}; })"
                            )
                            assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) <= 1
                            assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) <= 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                issues = page.evaluate(
                    "async () => (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v => v.id)"
                )
                assert not issues, (name, width, theme, issues)
                page.screenshot(path=f"artifacts/topology-table-{name}-{width}-{theme}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    inspect_view("filters", modal=True)
    page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(table.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    expect(table.get_by_role("cell", name="Edge-02", exact=True)).to_be_visible()
    expect(table.get_by_role("button", name="Filtreler (3)", exact=True)).to_be_visible()
    table.get_by_role("button", name="Filtreler (3)", exact=True).click()
    page.get_by_role("button", name="Koşul 3 sil", exact=True).click()
    page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(table.locator(".inventory-pagination")).to_contain_text("5 kayıt")
    table.get_by_role("button", name="Filtreler (2)", exact=True).click()
    page.get_by_role("button", name="Temizle", exact=True).click()
    page.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(table.get_by_role("button", name="Filtreler", exact=True)).to_be_visible()
    table.get_by_role("button", name="Sütunlar", exact=True).click()
    for checkbox in page.get_by_role("dialog").get_by_role("checkbox").all():
        checkbox.uncheck()
    expect(page.get_by_role("button", name="Sütunları uygula", exact=True)).to_be_disabled()
    for label in ["Kaynak cihaz", "Kaynak IP", "Komşu"]:
        page.get_by_role("checkbox", name=label, exact=True).check()
    inspect_view("columns", modal=True)
    page.get_by_role("button", name="Sütunları uygula", exact=True).click()
    assert table.get_by_role("columnheader").all_text_contents() == [
        "Kaynak cihaz",
        "Kaynak IP",
        "Komşu",
        "İşlemler",
    ]
    page.reload()
    expect(table.locator(".inventory-pagination")).to_contain_text("5 kayıt")
    assert table.get_by_role("columnheader").all_text_contents() == [
        "Kaynak cihaz",
        "Kaynak IP",
        "Komşu",
        "İşlemler",
    ]
    table.get_by_role("button", name="Sütunlar", exact=True).click()
    page.get_by_role("checkbox", name="Kaynak IP", exact=True).uncheck()
    page.keyboard.press("Escape")
    expect(table.get_by_role("button", name="Sütunlar", exact=True)).to_be_focused()
    expect(table.get_by_role("columnheader", name="Kaynak IP", exact=True)).to_be_visible()
    table.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("nonexistent-neighbor")
    expect(table.get_by_text("Bu koşullara uyan kayıt bulunamadı.", exact=True)).to_be_visible()
    table.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("")
    expect(table.locator(".inventory-pagination")).to_contain_text("5 kayıt")
    inspect_view("table")
    table.get_by_role("button", name="Kayıt ayrıntıları", exact=True).first.click()
    expect(page.get_by_role("dialog")).to_contain_text('"remote_name"')
    assert not errors, errors
    print(
        json.dumps(
            {
                "topology_table": "PASS",
                "and_or": "PASS",
                "columns_persist": "PASS",
                "screenshots": 18,
                "axe": "PASS",
                "console_errors": errors,
            }
        )
    )
    browser.close()
