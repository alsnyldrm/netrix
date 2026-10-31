"""Verify paired connection rows, responsive alignment, and real connection details."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    active = page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True)
    if active.get_attribute("aria-pressed") == "true":
        active.click()
    page.get_by_placeholder("Tüm alanlarda ara…").fill("SV-VW")
    same = page.get_by_role("row").filter(has=page.get_by_role("checkbox", name="192.0.2.55 seç", exact=True))
    dual = page.get_by_role("row").filter(has=page.get_by_role("checkbox", name="192.0.2.56 seç", exact=True))
    expect(same.get_by_role("cell", name="A7-B7", exact=True)).to_be_visible()
    expect(dual.locator(".ipam-connection-lines").first.locator("span")).to_have_text(
        ["HP-SW-BB-01-A-00-01", "HP-SW-BB-01-A-00-02"]
    )
    expect(dual.locator(".ipam-connection-lines").last.locator("span")).to_have_text(["I5", "A6"])
    Path("artifacts").mkdir(exist_ok=True)
    for width, height in [(1440, 1000), (375, 812)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ["light", "dark"]:
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            same.get_by_role("cell", name="A7-B7", exact=True).scroll_into_view_if_needed()
            pairs = dual.locator(".ipam-connection-lines").evaluate_all(
                "els=>els.map(e=>[...e.children].map(c=>({y:c.getBoundingClientRect().y,h:c.getBoundingClientRect().height})))"
            )
            assert pairs[0] == pairs[1], pairs
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/multi-{width}-{theme}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    same.get_by_role("button", name="192.0.2.55 IP ayrıntıları", exact=True).click()
    assert not errors and not any(reports.values()), (errors, reports)
    print(json.dumps({"paired_rows": "PASS", "axe": reports, "errors": errors}))
    browser.close()
