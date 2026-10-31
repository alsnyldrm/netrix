"""VM endpoint display and connection details; isolated fixture, no device queries."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True).click()
    expect(page.get_by_text("Ağ içindeki aktif IP adresleri", exact=True)).to_be_visible()
    expect(page.get_by_text("Yanıt vermeyen IP’ler doluluğa dahil edilmez.", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="192.0.2.2 düzenle", exact=True)).not_to_be_visible()
    expect(page.get_by_label("Ağ bloğu kullanımı")).to_contain_text("2 / 254 aktif IP")
    expect(page.get_by_label("Ağ bloğu kullanımı")).to_contain_text("%0.79 kullanım")
    page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True).click()
    expect(page.get_by_role("button", name="192.0.2.2 düzenle", exact=True)).to_be_visible()
    page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True).click()
    row = page.get_by_role("row").filter(has=page.get_by_role("checkbox", name="192.0.2.10 seç", exact=True))
    cell = row.get_by_role("cell", name="FBU-DS", exact=True)
    expect(cell).to_be_visible()
    expect(cell).to_have_text("FBU-DS")
    bond = page.get_by_role("row").filter(has=page.get_by_role("checkbox", name="192.0.2.65 seç", exact=True))
    expect(bond.get_by_role("cell", name="Fixture Backbone", exact=True)).to_be_visible()
    expect(bond.get_by_role("cell", name="Trk2", exact=True)).to_be_visible()
    expect(bond.get_by_role("cell", name="bond-server", exact=True)).to_be_visible()
    expect(row.get_by_role("cell", name="89", exact=True)).to_be_visible()
    Path("artifacts").mkdir(exist_ok=True)

    def check(name):
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
        )
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        page.screenshot(path=f"artifacts/endpoint-{name}.png")

    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            cell.scroll_into_view_if_needed()
            check(f"table-{width}-{theme}")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="192.0.2.10 IP ayrıntıları", exact=True).click()
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            expect(page.get_by_role("dialog")).to_be_visible()
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            check(f"detail-{width}-{theme}")
    assert not errors and not any(reports.values()), (errors, reports)
    print(
        json.dumps(
            {
                "endpoint": "PASS",
                "details": "source observations",
                "axe": reports,
                "console_errors": errors,
            }
        )
    )
    browser.close()
