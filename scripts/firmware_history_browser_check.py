"""Grouped execution history, lazy transcripts, safe output and responsive alignment."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:" + os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8260")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    errors, requests, reports = [], [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    page.goto(BASE + "/#firmware-history")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.locator(".fw-history-operation")).to_have_count(3)
    assert not any("/history/targets/" in url or "/targets?stage=" in url for url in requests)

    def check(name):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        if page.get_by_role("dialog").count():
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1"), name
        failures = page.locator(".fw-history-filters").evaluate_all("""groups => groups.flatMap(g=>{
            const r=[...g.querySelectorAll('input,select')].map(e=>e.getBoundingClientRect());
            return r.slice(1).filter((b,i)=>b.x>r[i].x+1 && (Math.abs(b.y-r[i].y)>1 || Math.abs(b.height-r[i].height)>1));
        })""")
        assert not failures, name
        alignment = page.locator(".fw-history-group > summary,.fw-history-device > summary").evaluate_all("""els=>els.filter(e=>e.getBoundingClientRect().width).flatMap(e=>{
            const icon=e.querySelector('svg').getBoundingClientRect(), name=e.querySelector('.fw-history-name').getBoundingClientRect();
            const style=getComputedStyle(e);return Math.abs(name.x - icon.right - parseFloat(style.gap))>1 ? ['name axis'] : [];
        })""")
        assert not alignment, (name, alignment)
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
        )
        page.screenshot(path=f"artifacts/firmware-history-{name}.png", full_page=True)

    for width in (1440, 1024, 768, 375):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"operations-{width}-{theme}")
            page.get_by_role("button", name="Fixture transcript operation", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.locator(".fw-history-group")).to_have_count(2)
            check(f"groups-{width}-{theme}")
            dialog.locator(".fw-history-group > summary").first.click()
            expect(dialog.locator(".fw-history-device")).to_have_count(2)
            dialog.locator(".fw-history-device > summary").first.click()
            expect(dialog.locator(".fw-history-event")).to_have_count(40)
            assert "fixture-output-secret" not in dialog.inner_text()
            expect(dialog.locator(".fw-history-metadata")).to_contain_text("PL.10.18.1010")
            dialog.locator(".fw-history-output > summary").first.click()
            expect(dialog.locator(".fw-history-output pre").first).to_contain_text("Active Image : primary")
            check(f"transcript-{width}-{theme}")
            if width == 1440 and theme == "light":
                dialog.locator(".fw-history-transcript").get_by_role(
                    "button", name="Sonraki", exact=True
                ).click()
                expect(dialog.locator(".fw-history-event")).to_have_count(5)
                expect(dialog.locator(".fw-history-transcript .fw-pager")).to_contain_text("41–45")
                dialog.locator(".fw-history-transcript").get_by_role(
                    "button", name="Önceki", exact=True
                ).click()
                expect(dialog.locator(".fw-history-event")).to_have_count(40)
                dialog.locator(".fw-history-device > summary").nth(1).click()
                expect(dialog.locator(".fw-history-failure")).to_contain_text(
                    "hedef yazılım alanında doğrulanamadı"
                )
                check("failure-and-two-devices")
            page.keyboard.press("Escape")

    for design in ("orbit", "terminal", "panorama", "focus"):
        for width in (1440, 375):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
            page.evaluate("d=>document.documentElement.dataset.design=d", design)
            page.get_by_role("button", name="Fixture transcript operation", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.locator(".fw-history-group > summary").first.click()
            expect(dialog.locator(".fw-history-device")).to_have_count(2)
            dialog.locator(".fw-history-device > summary").first.click()
            expect(dialog.locator(".fw-history-event")).to_have_count(40)
            check(f"design-{design}-{width}")
            page.keyboard.press("Escape")
    page.evaluate("()=>document.documentElement.dataset.design='atlas'")
    page.get_by_role("button", name="Fixture transcript operation", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.locator(".fw-history-group > summary").nth(1).click()
    expect(dialog.locator(".fw-history-device")).to_have_count(1)
    dialog.locator(".fw-history-device > summary").first.click()
    expect(dialog.locator(".fw-history-guide").last).to_contain_text("henüz işlem adımı kaydedilmedi")
    expect(dialog.locator(".fw-history-warning")).to_have_count(0)
    check("queued-device")
    page.keyboard.press("Escape")
    page.get_by_label("İşlem durumu", exact=True).select_option("cancelled")
    expect(page.locator(".fw-history-operation")).to_have_count(1)
    page.get_by_role("button", name="Fixture history plan", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.locator(".fw-history-group > summary").first.focus()
    page.keyboard.press("Enter")
    expect(dialog.locator(".fw-history-device")).to_have_count(1)
    dialog.locator(".fw-history-device > summary").first.focus()
    page.keyboard.press("Enter")
    expect(dialog.locator(".fw-history-warning")).to_contain_text("Bu eski işlemde")
    assert dialog.locator(".fw-history-command").count() == 0
    check("legacy-keyboard-mobile")
    page.keyboard.press("Escape")
    page.get_by_label("İşlem durumu", exact=True).select_option("")
    page.get_by_label("İşlem adı", exact=True).fill("does-not-exist")
    expect(page.locator(".fw-empty")).to_contain_text("eşleşen işlem kaydı bulunmuyor")
    check("filtered-empty")
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {
                "views": len(reports),
                "axe": reports,
                "page_errors": errors,
                "lazy_transcripts": True,
                "output_redaction": True,
                "event_pagination": True,
            }
        )
    )
    browser.close()
