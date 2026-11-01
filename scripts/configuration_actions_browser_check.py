"""Device-scoped comparison action placement on disposable data; no device traffic."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8215"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports, comparisons = [], {}, []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "request",
        lambda r: (
            comparisons.append(r.post_data_json)
            if r.method == "POST" and r.url.endswith("/configuration/compare")
            else None
        ),
    )
    page.goto(BASE + "/#configuration")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    actions = page.locator(".page-actions")
    Path("artifacts").mkdir(exist_ok=True)

    def check(key):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), key
        assert "Cihaz konfigürasyonlarını karşılaştır" not in page.content()
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[key] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
        )
        page.screenshot(path=f"artifacts/configuration-actions-{key}.png", full_page=True)

    for width, theme in ((1440, "light"), (1440, "dark"), (375, "light"), (375, "dark")):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        page.goto(BASE + "/#configuration")
        page.wait_for_load_state("networkidle")
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        expect(page.get_by_role("button", name="Switch 1", exact=True)).to_be_visible()
        expect(actions.get_by_role("button", name="Karşılaştır", exact=True)).to_have_count(0)
        check(f"directory-{width}-{theme}")
        page.get_by_role("button", name="Switch 1", exact=True).click()
        trigger = actions.get_by_role("button", name="Karşılaştır", exact=True)
        expect(trigger).to_be_visible()
        expect(
            page.locator(".backup-device-heading").get_by_role("button", name="Karşılaştır", exact=True)
        ).to_have_count(0)
        expect(page.locator("main").get_by_role("button", name="Karşılaştır", exact=True)).to_have_count(1)
        bounds = actions.locator("button").evaluate_all(
            "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,h:r.height,right:r.right}})"
        )
        assert (
            len(bounds) == 2
            and abs(bounds[0]["y"] - bounds[1]["y"]) < 1
            and abs(bounds[0]["h"] - bounds[1]["h"]) < 1
        ), bounds
        assert abs(bounds[1]["x"] - bounds[0]["right"] - 8) < 1, bounds
        check(f"history-{width}-{theme}")
        trigger.focus()
        page.keyboard.press("Enter")
        dialog = page.get_by_role("dialog")
        expect(
            dialog.get_by_role("heading", name="Kayıtlı konfigürasyonları karşılaştır", exact=True)
        ).to_be_visible()
        expect(dialog.get_by_role("combobox", name="Sol config dosyası")).to_be_visible()
        expect(dialog).to_contain_text("Sol · Switch 1")
        dialog.get_by_role("button", name="Karşılaştır", exact=True).click()
        expect(dialog.locator(".config-editor")).to_have_count(2)
        assert dialog.locator(".config-editor header strong").all_text_contents() == ["Switch 1", "Switch 1"]
        check(f"comparison-{width}-{theme}")
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        page.get_by_role("button", name="Cihazlara dön", exact=True).click()
        expect(actions.get_by_role("button", name="Karşılaştır", exact=True)).to_have_count(0)
        page.get_by_role("button", name="Switch 2", exact=True).click()
        actions.get_by_role("button", name="Karşılaştır", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("Sol · Switch 2")
        page.keyboard.press("Escape")
        page.goto(BASE + "/#backup-changes")
        expect(page.get_by_role("heading", name="Değişenler", exact=True)).to_be_visible()
        page.goto(BASE + "/#configuration")
        expect(page.get_by_role("button", name="Switch 1", exact=True)).to_be_visible()
        expect(actions.get_by_role("button", name="Karşılaştır", exact=True)).to_have_count(0)
    assert len(comparisons) == 4 and all(
        not r["distinct_devices"] and len(r["snapshot_ids"]) == 2 for r in comparisons
    ), comparisons
    assert not errors and not any(reports.values()), (errors, reports)
    print(
        json.dumps(
            {"device_actions": "PASS", "views": len(reports), "axe": reports, "console_errors": errors}
        )
    )
    browser.close()
