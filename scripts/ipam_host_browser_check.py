"""Real backend host/NIC matching, paired columns and responsive NIC details."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8215/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_placeholder("Tüm alanlarda ara…").fill("esxi-")
    same = page.get_by_role("row").filter(has=page.get_by_role("checkbox", name="192.0.2.20 seç", exact=True))
    dual = page.get_by_role("row").filter(has=page.get_by_role("checkbox", name="192.0.2.21 seç", exact=True))
    expect(same.get_by_role("cell", name="A1 - B2", exact=True)).to_be_visible()
    expect(dual.locator(".ipam-connection-lines").first.locator("span")).to_have_text(
        ["Switch 1", "Switch 2"]
    )
    expect(dual.locator(".ipam-connection-lines").last.locator("span")).to_have_text(["C3", "D4"])
    for width, height in [(1440, 1000), (375, 812), (812, 375)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            dual.scroll_into_view_if_needed()
            pairs = dual.locator(".ipam-connection-lines").evaluate_all(
                "els=>els.map(e=>[...e.children].map(c=>({y:c.getBoundingClientRect().y,h:c.getBoundingClientRect().height})))"
            )
            assert pairs[0] == pairs[1], pairs
            dual.get_by_role("button", name="192.0.2.21 IP ayrıntıları", exact=True).click()
            table = page.get_by_role("region", name="Fiziksel ağ kartları tablosu", exact=True)
            expect(table.get_by_role("row")).to_have_count(4)
            rows = table.get_by_role("row")
            expect(rows.nth(1)).to_contain_text("vmnic0")
            expect(rows.nth(1)).to_contain_text("Switch 1")
            expect(rows.nth(1)).to_contain_text("C3")
            expect(rows.nth(2)).to_contain_text("Switch 2")
            expect(rows.nth(2)).to_contain_text("D4")
            expect(rows.nth(3)).to_contain_text("Bağlı değil")
            table.scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"/tmp/netrix-host-nics-{width}-{theme}.png")
            page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_placeholder("Tüm alanlarda ara…").fill("physical-host")
    physical = page.get_by_role("row").filter(
        has=page.get_by_role("checkbox", name="192.0.2.22 seç", exact=True)
    )
    expect(physical.get_by_role("cell", name="A7 / B7", exact=True)).to_be_visible()
    physical.get_by_role("button", name="192.0.2.22 IP ayrıntıları", exact=True).click()
    table = page.get_by_role("region", name="Fiziksel ağ kartları tablosu", exact=True)
    expect(table.get_by_role("row")).to_have_count(3)
    expect(table).to_contain_text("00:55:66:00:00:02")
    expect(table).to_contain_text("00:55:66:00:00:03")
    for width, height in ((1440, 1000), (375, 812)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            table.scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            reports[f"ssh-{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"/tmp/netrix-ssh-peer-{width}-{theme}.png")
    assert not errors and not any(reports.values()), (errors, reports)
    print(json.dumps({"host_nics": "PASS", "paired_switch_ports": "PASS", "axe": reports, "errors": errors}))
    browser.close()
