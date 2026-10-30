"""Device-first backup navigation against a disposable fixture; no device traffic."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8205"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, snapshots, comparisons = [], [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: snapshots.append(r.url) if "/inventory/snapshots?" in r.url else None)
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#configuration")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("2 cihaz")
    assert not snapshots, snapshots
    reports = {}
    Path("artifacts").mkdir(exist_ok=True)

    def check_screen(key):
        for theme, width, height in (("light", 1440, 1000), ("dark", 375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), key
            boxes = page.locator(".inventory-toolbar > button").evaluate_all(
                "els=>els.map(e=>{const r=e.getBoundingClientRect();return {y:r.y,h:r.height};})"
            )
            assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) <= 1, boxes
            assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) <= 1, boxes
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            report = page.evaluate(
                "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
            )
            reports[f"{key}-{theme}"] = [v["id"] for v in report["violations"]]
            page.screenshot(path=f"artifacts/backup-device-{key}-{theme}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    for key in ("configuration", "backup-compare"):
        page.goto(BASE + "/#" + key)
        expect(page.locator(".inventory-pagination")).to_contain_text("2 cihaz")
        expect(page.get_by_role("columnheader", name="Yedek sayısı", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Görüntüle", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Aktif config ile karşılaştır", exact=True)).to_have_count(0)
        search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
        search.fill("192.0.2.2")
        expect(page.locator(".inventory-pagination")).to_contain_text("1 cihaz")
        expect(page.get_by_role("button", name="Fixture 01 yedekleri", exact=True)).to_be_visible()
        search.fill("")
        expect(page.locator(".inventory-pagination")).to_contain_text("2 cihaz")
        check_screen(key + "-directory")
        # Keyboard can open the same drill-down as the mouse.
        page.get_by_role("button", name="Fixture 00 yedekleri", exact=True).focus()
        page.keyboard.press("Enter")
        expect(page.get_by_role("heading", name="Fixture 00", exact=True)).to_be_focused()
        expect(page.locator(".inventory-pagination")).to_contain_text("2 kayıt")
        expect(page.locator("tbody")).not_to_contain_text("Fixture 01")
        expect(page.get_by_label("Grupla", exact=True)).to_have_count(0)
        check_screen(key + "-history")
        page.get_by_role("button", name="Cihazlara dön", exact=True).click()
        expect(page.locator(".inventory-pagination")).to_contain_text("2 cihaz")
        page.get_by_role("button", name="Fixture 01 yedekleri", exact=True).click()
        expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")
        expect(page.locator("tbody")).not_to_contain_text("Fixture 00")
        if key == "backup-compare":

            def compare(route):
                comparisons.append(route.request.url)
                route.fulfill(json={"id": "fixture-comparison", "status": "queued"}, status=202)

            page.route("**/api/v1/snapshots/*/compare-live", compare)
            page.route(
                "**/api/v1/backup-comparisons/fixture-comparison",
                lambda r: r.fulfill(
                    json={
                        "id": "fixture-comparison",
                        "status": "succeeded",
                        "result": {
                            "changed": True,
                            "diff": "+hostname fixture-live",
                            "checked_at": "2026-10-30T08:00:00Z",
                        },
                    }
                ),
            )
            page.get_by_role("button", name="Aktif config ile karşılaştır", exact=True).click()
            expect(page.get_by_role("dialog")).to_contain_text("Fixture 01")
            expect(page.locator(".backup-result pre")).to_contain_text("+hostname fixture-live")
            page.keyboard.press("Escape")
        page.get_by_role("button", name="Cihazlara dön", exact=True).click()
    assert snapshots and all("device_id=" in url for url in snapshots), snapshots
    assert len(comparisons) == 1
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {
                "device_first_backups": "PASS",
                "scoped_history_requests": len(snapshots),
                "axe": reports,
                "errors": errors,
            }
        )
    )
    browser.close()
