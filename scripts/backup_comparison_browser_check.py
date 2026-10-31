"""Comparison status/cancellation regressions on a disposable fixture, no device traffic."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8205"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#backup-compare")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="Fixture 00 yedekleri", exact=True).click()
    state = {"id": "comparison-fixture", "status": "queued", "result": {}}
    admission_error = False

    def start(route):
        route.fulfill(
            status=503 if admission_error else 202,
            json={"detail": "İşlem hizmeti hazır değil. İstek sıraya alınmadı."}
            if admission_error
            else state,
        )

    page.route("**/api/v1/snapshots/*/compare-live", start)
    page.route("**/api/v1/backup-comparisons/comparison-fixture", lambda r: r.fulfill(json=state))

    def cancel(route):
        state.update(status="cancelled", cancel_requested=True)
        route.fulfill(json=state)

    page.route("**/api/v1/jobs/comparison-fixture/cancel", cancel)
    Path("artifacts").mkdir(exist_ok=True)
    trigger = page.get_by_role("button", name="Aktif config ile karşılaştır", exact=True).first
    for width, theme in ((1440, "light"), (375, "dark")):
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        state.update(status="queued", cancel_requested=False, error="")
        trigger.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_role("status")).to_contain_text("henüz cihaza bağlanılmadı")
        expect(dialog.get_by_role("status")).not_to_contain_text("SSH üzerinden okunuyor")
        state["status"] = "running"
        expect(dialog.get_by_role("status")).to_contain_text("SSH üzerinden okunuyor", timeout=5000)
        expect(dialog).to_contain_text("en fazla 90 saniye")
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        edges = dialog.locator(".backup-result > p, .backup-result > button").evaluate_all(
            "els=>els.map(e=>e.getBoundingClientRect().left)"
        )
        assert max(edges) - min(edges) < 1, edges
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[theme] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
        )
        page.screenshot(path=f"artifacts/comparison-running-{width}.png", full_page=True)
        dialog.get_by_role("button", name="Karşılaştırmayı iptal et", exact=True).click()
        expect(dialog.get_by_role("status")).to_have_text("Karşılaştırma iptal edildi.")
        expect(dialog.get_by_role("button", name="Karşılaştırmayı iptal et", exact=True)).to_have_count(0)
        page.keyboard.press("Escape")
        admission_error = True
        trigger.click()
        expect(dialog.get_by_role("alert")).to_contain_text("İstek sıraya alınmadı")
        expect(dialog.get_by_role("button", name="Karşılaştırmayı iptal et", exact=True)).to_have_count(0)
        page.keyboard.press("Escape")
        admission_error = False
        state.update(status="running", cancel_requested=False)
        trigger.click()
        expect(dialog.get_by_role("status")).to_contain_text("SSH üzerinden okunuyor")
        state.update(status="failed", error="Cihaz yanıtı zaman aşımına uğradı.")
        expect(dialog.get_by_role("status")).to_contain_text("zaman aşımına")
        page.keyboard.press("Escape")
        state.update(
            status="succeeded", result={"changed": False, "diff": "", "checked_at": "2026-11-01T00:00:00Z"}
        )
        trigger.click()
        expect(dialog.get_by_role("status")).to_have_text("Konfigürasyon aynı.")
        expect(dialog.locator("pre")).to_have_text("Fark yok.")
        page.keyboard.press("Escape")
    assert not errors, errors
    assert not any(reports.values()), reports
    print(json.dumps({"comparison_states": "PASS", "axe": reports, "errors": errors}))
    browser.close()
