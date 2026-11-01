"""Read-only version fields against the disposable software_version_fixture."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    Path("artifacts").mkdir(exist_ok=True)
    page.goto("http://127.0.0.1:8244/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("columnheader", name="Versiyon", exact=False)).to_be_visible()
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("KB.16.11.0032")
    expect(page.get_by_role("cell", name="KB.16.11.0032", exact=True)).to_be_visible()
    expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")

    def check(name):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                target = (
                    page.locator(".device-software-version")
                    if page.get_by_role("dialog").count()
                    else page.get_by_role("cell", name="KB.16.11.0032", exact=True)
                )
                target.scroll_into_view_if_needed()
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                if page.get_by_role("dialog").count():
                    assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
                    assert target.evaluate(
                        "e=>{let r=e.getBoundingClientRect(),g=e.parentElement.getBoundingClientRect();return Math.abs(r.width-g.width)<3}"
                    )
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/software-version-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    check("inventory")
    page.get_by_role("button", name="Fixture 00", exact=True).click()
    expect(page.locator(".device-software-version dt")).to_have_text("Versiyon")
    expect(page.locator(".device-software-version dd")).to_have_text("KB.16.11.0032")
    check("detail")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Fixture 01")
    page.get_by_role("button", name="Fixture 01", exact=True).click()
    expect(page.locator(".device-software-version dd")).to_have_text("—")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"software_version": "PASS", "axe": reports, "errors": errors}))
    browser.close()
