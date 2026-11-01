"""Gateway settings and indicators against scripts.archive_fixture only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8243")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda s: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    Path("artifacts").mkdir(exist_ok=True)

    def check(name, form=False):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                dialog = page.get_by_role("dialog")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                if dialog.count():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                if form:
                    control = page.get_by_role("checkbox", name="Gateway olarak işaretle", exact=True)
                    control.scroll_into_view_if_needed()
                    box = control.locator("..").bounding_box()
                    assert box["height"] >= 40
                    assert control.locator("xpath=ancestor::label").bounding_box()["height"] >= 44
                    if width == 1440:
                        boxes = dialog.locator(".form-grid > .form-field").evaluate_all(
                            "els=>els.map(e=>{let r=(e.querySelector('.checkbox-control')||e.querySelector('input,select')).getBoundingClientRect();return {y:r.y,h:r.height}})"
                        )
                        # Adjacent controls in each two-column row share the same axis.
                        for left, right in zip(boxes[::2], boxes[1::2]):
                            assert abs(left["y"] - right["y"]) < 1
                            assert abs(left["h"] - right["h"]) < 1
                if name.startswith("detail"):
                    grid = dialog.locator(".detail-grid")
                    expect(
                        grid.locator(
                            ":scope > div:not(.device-cabinet-location):not(.device-software-version)"
                        )
                    ).to_have_count(6)
                    boxes = grid.locator(
                        ":scope > div:not(.device-cabinet-location):not(.device-software-version)"
                    ).evaluate_all(
                        "els=>els.map(e=>{let r=e.getBoundingClientRect();return {y:r.y,w:r.width,h:r.height}})"
                    )
                    assert max(b["w"] for b in boxes) - min(b["w"] for b in boxes) < 1
                    assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) < 1
                    if width == 1440:
                        for chunk in (boxes[:3], boxes[3:]):
                            assert max(b["y"] for b in chunk) - min(b["y"] for b in chunk) < 1
                            assert max(b["h"] for b in chunk) - min(b["h"] for b in chunk) < 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))"
                )
                page.screenshot(path=f"artifacts/gateway-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(base + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Fixture 00")
    row = page.get_by_role("row").filter(has=page.get_by_role("button", name="Fixture 00", exact=True))
    expect(row).to_be_visible()
    expect(row.locator(".badge").filter(has_text="Gateway")).to_have_count(0)
    row.get_by_role("button", name="Kaydı düzenle", exact=True).click()
    checkbox = page.get_by_role("checkbox", name="Gateway olarak işaretle", exact=True)
    expect(checkbox).not_to_be_checked()
    checkbox.focus()
    page.keyboard.press("Space")
    expect(checkbox).to_be_checked()
    check("settings", form=True)
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(row).to_have_class("gateway-device-row")
    expect(row.locator(".badge.active").filter(has_text="Gateway")).to_be_visible()
    assert row.locator(".inventory-device-name > button").evaluate(
        "e=>{const s=document.createElement('span');s.style.color='var(--success)';e.append(s);const ok=getComputedStyle(e).color===getComputedStyle(s).color;s.remove();return ok}"
    )
    check("inventory")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Fixture 00")
    expect(row).to_have_class("gateway-device-row")
    row.get_by_role("button", name="Fixture 00", exact=True).click()
    gateway = page.locator(".detail-grid > div").filter(has=page.get_by_text("Gateway Cihazı", exact=True))
    expect(gateway.locator("dd .badge.active")).to_have_text("Evet")
    check("detail-yes")
    page.get_by_role("button", name="Düzenle", exact=True).click()
    checkbox.uncheck()
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(row).not_to_have_class("gateway-device-row")
    expect(row.locator(".badge").filter(has_text="Gateway")).to_have_count(0)
    row.get_by_role("button", name="Fixture 00", exact=True).click()
    expect(gateway.locator("dd .badge.failed")).to_have_text("Hayır")
    check("detail-no")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"gateway_ui": "PASS", "axe": reports, "errors": errors}))
    browser.close()
