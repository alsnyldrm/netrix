"""Group picker: bulk selection across pages, advanced filters and exclusive ownership; fixture only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = "http://127.0.0.1:" + os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8250")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/#firmware-groups")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="Grup oluştur", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Grup adı", exact=True).fill("Bulk browser")
    dialog.locator("summary").click()

    def check(name):
        assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth"), name
        assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), name
        controls = dialog.locator(
            ".fw-picker-filters[open] .fw-fields label > input, .fw-picker-filters[open] .fw-fields label > select"
        ).evaluate_all(
            "els => els.map(e => {const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}})"
        )
        for a, b in zip(controls, controls[1:]):
            if b["x"] > a["x"] + 1:
                assert abs(a["y"] - b["y"]) < 1 and abs(a["h"] - b["h"]) < 1, (name, controls)
        actions = dialog.locator(
            ".fw-selection-actions > label, .fw-selection-actions > button"
        ).evaluate_all("""elements => elements.map(element => {
          const box=element.getBoundingClientRect();
          const walker=document.createTreeWalker(element.matches('label') ? element.querySelector('span') : element,NodeFilter.SHOW_TEXT);
          let node; while(node=walker.nextNode()) { if(!node.textContent.trim()) continue; const range=document.createRange(); range.selectNodeContents(node); const text=range.getBoundingClientRect(); return {y:box.y,cy:text.y+text.height/2}; }
        }).filter(Boolean)""")
        for a, b in zip(actions, actions[1:]):
            if abs(a["y"] - b["y"]) <= 3:
                assert abs(a["cy"] - b["cy"]) <= 2, (name, actions)
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
        )
        page.screenshot(path=f"artifacts/firmware-groups-{name}.png", full_page=True)

    dialog.get_by_label("Cihaz ailesi", exact=True).select_option("cx6100")
    expect(dialog.locator(".fw-checklist input")).to_have_count(1)
    expect(dialog.locator(".fw-checklist input")).to_be_disabled()
    expect(dialog.locator(".fw-checklist")).to_contain_text("Mevcut grup: Fixture group")
    expect(dialog.get_by_role("button", name="Filtredeki tüm uygunları seç", exact=True)).to_be_disabled()
    for width in (1440, 1024, 768, 375):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": 1000 if width >= 1024 else 812})
            page.evaluate("v => document.documentElement.dataset.theme=v", theme)
            dialog.locator("summary").scroll_into_view_if_needed()
            check(f"filters-{width}-{theme}")
            dialog.locator(".fw-selection-bar").scroll_into_view_if_needed()
            check(f"selection-{width}-{theme}")
    page.set_viewport_size({"width": 1440, "height": 1000})
    dialog.get_by_label("Grup üyeliği", exact=True).select_option("available")
    expect(dialog.locator(".fw-checklist input")).to_have_count(0)
    expect(dialog.locator(".fw-checklist")).to_contain_text("Filtrelere uygun cihaz bulunamadı")
    dialog.get_by_role("button", name="Filtreleri temizle", exact=True).click()
    dialog.get_by_label("Cihaz ara", exact=True).fill("Fixture 00")
    expect(dialog.locator(".fw-checklist input")).to_have_count(50)
    dialog.get_by_label("Cihaz ara", exact=True).press("Enter")
    expect(dialog).to_be_visible()
    assert not any(
        g["name"] == "Bulk browser"
        for g in page.request.get(base + "/api/v1/firmware/groups").json()["items"]
    )
    dialog.get_by_role("checkbox", name="Bu sayfadaki uygun cihazları seç", exact=True).check()
    expect(dialog.locator(".fw-selection-bar")).to_contain_text("50 cihaz seçildi")
    dialog.get_by_role("button", name="Sonraki", exact=True).click()
    expect(dialog.locator(".fw-checklist input").first).not_to_be_checked()
    expect(dialog.locator(".fw-selection-bar")).to_contain_text("50 cihaz seçildi")
    dialog.get_by_role("button", name="Filtredeki tüm uygunları seç", exact=True).click()
    expect(dialog.locator(".fw-selection-bar")).to_contain_text("100 cihaz seçildi")
    expect(
        dialog.get_by_role("checkbox", name="Bu sayfadaki uygun cihazları seç", exact=True)
    ).to_be_checked()
    dialog.get_by_label("Cihaz ara", exact=True).fill("Fixture 0000")
    expect(dialog.locator(".fw-checklist input")).to_have_count(1)
    dialog.locator(".fw-checklist input").uncheck()
    expect(dialog.locator(".fw-selection-bar")).to_contain_text("99 cihaz seçildi")
    dialog.get_by_role("button", name="Seçimleri temizle", exact=True).click()
    expect(dialog.locator(".fw-selection-bar")).to_contain_text("0 cihaz seçildi")
    dialog.locator(".fw-checklist input").check()
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(dialog).to_have_count(0)
    row = page.locator(".fw-workspace tbody tr").filter(has_text="Bulk browser")
    row.get_by_role("button", name="Düzenle", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Cihaz ara", exact=True).fill("Fixture 0000")
    expect(dialog.locator(".fw-checklist input")).to_have_count(1)
    expect(dialog.locator(".fw-checklist input")).to_be_enabled()
    expect(dialog.locator(".fw-checklist input")).to_be_checked()
    expect(dialog.locator(".fw-checklist")).to_contain_text("Bu grubun üyesi")
    dialog.locator(".fw-checklist input").uncheck()
    dialog.locator(".fw-checklist input").check()
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        check(f"own-members-{width}")
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="Grup oluştur", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Grup adı", exact=True).fill("Must reject race")
    dialog.get_by_label("Cihaz ara", exact=True).fill("Fixture 0001")
    expect(dialog.locator(".fw-checklist input")).to_have_count(1)
    dialog.locator(".fw-checklist input").check()
    candidate = page.request.get(base + "/api/v1/firmware/devices?q=Fixture%200001").json()["items"][0]
    response = page.request.post(
        base + "/api/v1/firmware/groups",
        headers={"X-Netrix-Request": "1"},
        data={"name": "Concurrent fixture owner", "device_ids": [candidate["id"]]},
    )
    assert response.status == 201, response.text()
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Concurrent fixture owner")
    expect(dialog.get_by_label("Grup adı", exact=True)).to_have_value("Must reject race")
    expect(dialog.locator(".fw-selection-bar")).to_contain_text("1 cihaz seçildi")
    groups = page.request.get(base + "/api/v1/firmware/groups").json()["items"]
    assert not any(g["name"] == "Must reject race" for g in groups)
    check("race-rejection")
    assert not errors and not any(reports.values()), {"errors": errors, "axe": reports}
    print(
        json.dumps(
            {
                "views": len(reports),
                "axe": reports,
                "page_errors": errors,
                "bulk_count": 100,
                "cross_page_selection": True,
                "ownership_conflict_retains_form": True,
            }
        )
    )
    browser.close()
