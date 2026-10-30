"""Check sortable topology headers against scripts/topology_fixture.py."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8225")
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
    directory = page.get_by_role("region", name="Bağlantı cihazları")
    expect(directory.locator(".inventory-pagination")).to_contain_text("5 cihaz")

    def sort(table, label, field, direction, keyboard=False):
        button = table.get_by_role(
            "button", name=f"{label}: {'artan' if direction == 'asc' else 'azalan'} sırala", exact=True
        )
        with page.expect_response(
            lambda r: (
                "/inventory/" in r.url
                and f"sort_by={field}" in r.url
                and f"sort_direction={direction}" in r.url
            )
        ) as response:
            if keyboard:
                button.focus()
                button.press("Enter")
            else:
                button.click()
        assert response.value.ok
        result = response.value.json()
        expect(table.get_by_role("columnheader", name=label, exact=True)).to_have_attribute(
            "aria-sort", "ascending" if direction == "asc" else "descending"
        )
        expect(table.get_by_text("Kayıtlar yükleniyor…", exact=True)).to_have_count(0)
        return result["items"]

    rows = sort(directory, "Ad", "name", "asc", keyboard=True)
    assert [row["name"] for row in rows] == sorted(row["name"] for row in rows)
    rows = sort(directory, "Ad", "name", "desc")
    assert [row["name"] for row in rows] == sorted((row["name"] for row in rows), reverse=True)
    directory.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True).click()
    table = page.get_by_role("region", name="Bağlantı kayıtları")
    expect(table.locator(".inventory-pagination")).to_contain_text("4 kayıt")
    for label, field in [
        ("Komşu", "remote_name"),
        ("Yerel port", "interface_name"),
        ("Güven (%)", "confidence_percent"),
    ]:
        for direction in ("asc", "desc"):
            rows = sort(table, label, field, direction)
            values = [row[field] for row in rows if row[field] is not None]
            assert values == sorted(values, reverse=direction == "desc")
    table.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Edge")
    expect(table.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    rows = sort(table, "Komşu", "remote_name", "asc")
    assert len(rows) == 1 and rows[0]["remote_name"] == "Edge-01"
    table.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("")
    expect(table.locator(".inventory-pagination")).to_contain_text("4 kayıt")
    for width, height in [(1440, 1000), (375, 812), (812, 375)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("light", "dark"):
            page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            boxes = table.locator(".column-sort").evaluate_all(
                "els => els.map(e => {const r=e.getBoundingClientRect();return {y:r.y,h:r.height,w:r.width};})"
            )
            assert all(b["h"] >= 44 and b["w"] >= 44 for b in boxes)
            assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) <= 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async () => (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            assert not violations, (width, theme, violations)
            table.screenshot(path=f"artifacts/sorting-{width}-{theme}.png")
    assert not errors, errors
    print(
        json.dumps(
            {
                "headers_keyboard_sorting": "PASS",
                "search_scope": "PASS",
                "desktop_mobile_landscape_themes_axe": "PASS",
                "errors": errors,
            }
        )
    )
    browser.close()
