"""Archive/restore end-to-end check against the disposable inventory fixture only."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8205"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    Path("artifacts").mkdir(exist_ok=True)

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                dialog = page.get_by_role("dialog")
                if dialog.count():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                    boxes = dialog.locator(".dialog-footer button").evaluate_all(
                        "els=>els.map(e=>{const b=e.getBoundingClientRect();return {y:b.y,h:b.height}})"
                    )
                    assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) <= 1
                    assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) <= 1
                else:
                    controls = page.locator(".inventory-toolbar > button").evaluate_all(
                        "els=>els.map(e=>{const b=e.getBoundingClientRect();return {y:b.y,h:b.height}})"
                    )
                    assert max(b["h"] for b in controls) - min(b["h"] for b in controls) <= 1
                    if width == 1440:
                        assert max(b["y"] for b in controls) - min(b["y"] for b in controls) <= 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                reports[f"{name}-{width}-{theme}"] = violations
                page.screenshot(path=f"artifacts/archive-{name}-{width}-{theme}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
    expect(page.locator(".inventory-pagination")).to_contain_text("35 kayıt")
    search.fill("Fixture 00")
    page.get_by_role("checkbox", name="Fixture 00 seç", exact=True).check()
    page.get_by_role("button", name="Sil", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("Arşivlenmiş cihazlar")
    check("archive-confirm")
    page.get_by_role("button", name="Seçilenleri arşivle", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    expect(page.locator("p[role=status]")).to_contain_text("1 cihaz arşivlendi")
    page.get_by_role("button", name="Arşivlenmiş cihazlar", exact=True).click()
    expect(page.get_by_role("heading", name="Arşivlenmiş cihazlar", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Fixture 00", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Yeni kayıt", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="İçeri Aktar", exact=True)).to_have_count(0)
    search.fill("192.0.2.1")
    expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    check("list")
    page.get_by_role("button", name="Sütunlar", exact=True).click()
    page.get_by_role("checkbox", name="VRF", exact=True).check()
    page.get_by_role("button", name="Sütunları uygula", exact=True).click()
    expect(page.get_by_role("columnheader", name="VRF", exact=True)).to_be_visible()
    page.get_by_role("button", name="Fixture 00 geri yükle", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("Bakımda")
    check("restore-confirm")
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    expect(page.get_by_role("cell", name="Fixture 00", exact=True)).to_be_visible()
    page.get_by_role("button", name="Fixture 00 geri yükle", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Geri yükle", exact=True).click()
    expect(page.locator("p[role=status]")).to_contain_text("1 cihaz geri yüklendi")
    expect(page.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    check("restored-empty")
    page.get_by_role("button", name="Cihaz envanteri", exact=True).click()
    search.fill("Fixture 00")
    expect(page.get_by_role("cell", name="Bakımda", exact=True)).to_be_visible()
    page.get_by_role("button", name="Fixture 00 ayrıntıları", exact=True).click()
    expect(page.get_by_role("checkbox", name="port1 uygulamaya ekle", exact=True)).to_be_checked()
    page.keyboard.press("Escape")
    # Bulk restore uses the same atomic endpoint and survives a page reload.
    search.fill("")
    for name in ("Fixture 33", "Fixture 34"):
        page.get_by_role("checkbox", name=name + " seç", exact=True).check()
    page.get_by_role("button", name="Sil", exact=True).click()
    page.get_by_role("button", name="Seçilenleri arşivle", exact=True).click()
    expect(page.locator("p[role=status]")).to_contain_text("2 cihaz arşivlendi")
    page.get_by_role("button", name="Arşivlenmiş cihazlar", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    page.get_by_role("checkbox", name="Bu sayfadaki kayıtları seç", exact=True).check()
    page.locator(".inventory-selection").get_by_role("button", name="Toplu geri yükle", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("2 cihaz")
    page.get_by_role("dialog").get_by_role("button", name="Geri yükle", exact=True).click()
    expect(page.locator("p[role=status]")).to_contain_text("2 cihaz geri yüklendi")
    page.reload()
    expect(page.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"archive_restore": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
