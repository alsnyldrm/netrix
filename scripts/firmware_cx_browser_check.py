"""CX digest progress and staged result; disposable API fixture only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:" + os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8273")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#firmware-plans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_role("button", name="Fixture paused plan", exact=True)).to_be_visible()
    state = {"staged": False}

    def detail(route):
        response = route.fetch()
        data = response.json()
        if data.get("name") == "Fixture paused plan":
            data["status"], data["mode"] = ("ready" if state["staged"] else "running"), "stage"
            for target in data["targets"]:
                target.update(
                    status="staged" if state["staged"] else "running",
                    phase="image_verifying",
                    error="",
                    error_code="",
                    transfer_bytes=285115183,
                )
                target["evidence"]["image_verification_percent"] = 100 if state["staged"] else 50
        route.fulfill(response=response, json=data)

    page.route("**/api/v1/firmware/plans/*", detail)
    for width in (1440, 375):
        for theme in ("light", "dark"):
            for staged in (False, True):
                state["staged"] = staged
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.get_by_role("button", name="Fixture paused plan", exact=True).click()
                dialog = page.get_by_role("dialog")
                if staged:
                    expect(dialog.locator("tbody")).to_contain_text("Hedef firmware yazılım alanında hazır.")
                else:
                    expect(dialog.locator("tbody")).to_contain_text("Cihazın imajı doğrulanıyor")
                    expect(dialog.locator("tbody")).to_contain_text(
                        "Dosya aktarıldı; cihazın SHA-256 kontrolü sürüyor. %50"
                    )
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
                tops = (
                    dialog.locator("tbody tr")
                    .first.locator(".fw-cell-primary")
                    .evaluate_all("els=>els.map(e=>e.getBoundingClientRect().top)")
                )
                assert max(tops) - min(tops) <= 1, tops
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                name = f"{width}-{theme}-{'staged' if staged else 'sha-progress'}"
                reports[name] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/firmware-cx-{name}.png", full_page=True)
                page.keyboard.press("Escape")

    def transcript(route):
        response = route.fetch()
        data = response.json()
        t = data["target"]
        t["evidence"].update(
            image_verification_percent=100 if state["staged"] else 50,
            staged=state["staged"],
            staged_sha256="a" * 64 if state["staged"] else "",
        )
        route.fulfill(response=response, json=data)

    page.route("**/api/v1/firmware/history/targets/*", transcript)
    page.goto(BASE + "/#firmware-history")
    for width in (1440, 375):
        for theme in ("light", "dark"):
            for staged in (False, True):
                state["staged"] = staged
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.get_by_role("button", name="Fixture transcript operation", exact=True).click()
                dialog = page.get_by_role("dialog")
                dialog.locator(".fw-history-group > summary").first.click()
                expect(dialog.locator(".fw-history-device")).to_have_count(2)
                dialog.locator(".fw-history-device > summary").first.click()
                expect(dialog.locator(".fw-history-metadata")).to_contain_text(
                    "SHA-256 eşleşti; imaj hazır." if staged else "SHA-256 doğrulaması: %50"
                )
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                name = f"history-{width}-{theme}-{'staged' if staged else 'sha-progress'}"
                reports[name] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/firmware-cx-{name}.png", full_page=True)
                page.keyboard.press("Escape")
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {"views": len(reports), "axe": reports, "page_errors": errors, "progress_and_staged_result": True}
        )
    )
    browser.close()
