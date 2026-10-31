"""Organizer CRUD, collision feedback and responsive cabinet rendering; isolated fixture."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#cabinets")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="K-04", exact=True).click()
    start = page.get_by_label("Organizer başlangıç U", exact=True)
    height = page.get_by_label("Organizer yüksekliği (U)", exact=True)
    start.fill("11")
    page.get_by_role("button", name="Organizer ekle", exact=True).click()
    expect(page.get_by_text("Organizer kaydedildi.", exact=True)).to_be_visible()
    diagram = page.get_by_role("img", name="Fırçalı organizer şeması", exact=True)
    expect(diagram).to_be_attached()
    start.fill("11")
    page.get_by_role("button", name="Organizer ekle", exact=True).click()
    expect(page.locator("#organizer-error")).to_contain_text("kullanılıyor")
    expect(start).to_have_value("11")
    page.get_by_role("button", name="Fırçalı organizer yerleşimini düzenle", exact=True).click()
    expect(start).to_be_focused()
    start.fill("9")
    height.fill("2")
    page.get_by_role("button", name="Organizeri güncelle", exact=True).click()
    expect(page.get_by_text("Organizer kaydedildi.", exact=True)).to_be_visible()
    expect(page.get_by_text("9–10 U", exact=True)).to_be_attached()
    for width, tall in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": tall})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            page.get_by_role("button", name="Organizer ekle", exact=True).scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            boxes = page.locator(".rack-organizer-form input").evaluate_all(
                "es=>es.map(e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height}})"
            )
            assert abs(boxes[0]["width"] - boxes[1]["width"]) < 1
            assert abs(boxes[0]["height"] - boxes[1]["height"]) < 1
            if width > 700:
                assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1
            page.evaluate(Path("frontend/node_modules/axe-core/axe.min.js").read_text())
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/organizer-form-{width}-{theme}.png")
            diagram.scroll_into_view_if_needed()
            expect(diagram).to_be_visible()
            page.screenshot(path=f"artifacts/organizer-rack-{width}-{theme}.png")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="K-04", exact=True).click()
    expect(page.get_by_text("9–10 U", exact=True)).to_be_attached()
    page.get_by_role("button", name="Fırçalı organizer kabinetten çıkar", exact=True).click()
    expect(diagram).to_have_count(0)
    assert not errors and not any(reports.values()), (errors, reports)
    print(
        json.dumps(
            {"organizer_add_edit_delete_reload_collision": "PASS", "axe": reports, "console_errors": errors}
        )
    )
    browser.close()
