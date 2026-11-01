"""Physical location facts on the disposable rooms fixture only."""

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
    page.goto("http://127.0.0.1:8215/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="Switch 1", exact=True).click()
    section = page.locator(".device-cabinet-location")
    expect(section.locator(":scope > dt")).to_have_text("Tam kabin yolu")
    for label, value in {
        "Lokasyon": "Kuzey Kampüs",
        "Kat": "L-0",
        "Bölüm": "A",
        "Oda ismi": "Sunucu Odası",
        "Kabin": "4",
        "U no": "13U",
    }.items():
        cell = section.locator(".cabinet-location-grid > div").filter(has=page.get_by_text(label, exact=True))
        expect(cell.locator("dd")).to_have_text(value)

    def check(name):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                section.scroll_into_view_if_needed()
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
                assert page.locator(".device-facts").evaluate(
                    "e=>{const p=e.parentElement,r=e.getBoundingClientRect(),b=p.getBoundingClientRect(),s=getComputedStyle(p);return r.left>=b.left+parseFloat(s.paddingLeft)-1&&r.right<=b.right-parseFloat(s.paddingRight)+1}"
                )
                cells = section.locator(".cabinet-location-grid > div")
                expect(cells).to_have_count(6)
                boxes = cells.evaluate_all(
                    "els=>els.map(e=>{let r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
                )
                columns = 2 if width <= 640 else 3
                for n in range(0, 6, columns):
                    row = boxes[n : n + columns]
                    assert max(b["y"] for b in row) - min(b["y"] for b in row) < 1
                    assert max(b["w"] for b in row) - min(b["w"] for b in row) < 1
                if width > 640:
                    axes = page.locator(".device-facts > div:not(.device-cabinet-location)").evaluate_all(
                        "els=>els.slice(0,3).map(e=>e.getBoundingClientRect().x)"
                    )
                    assert all(abs(a - b["x"]) < 1 for a, b in zip(axes, boxes[:3]))
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/device-rack-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    check("placed")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="Switch 2", exact=True).click()
    expect(section).to_contain_text("Bu cihazın kayıtlı kabin yerleşimi yok.")
    expect(section.locator(".cabinet-location-grid dd")).to_have_text(["—"] * 6)
    check("unplaced")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"rack_details": "PASS", "axe": reports, "errors": errors}))
    browser.close()
