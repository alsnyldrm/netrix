"""Gateway checkbox, persistence and colors on isolated desktop/mobile browsers."""

import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8215/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    row = page.get_by_role("row").filter(has=page.get_by_role("button", name="192.0.2.10", exact=True))
    address = row.get_by_role("button", name="192.0.2.10", exact=True)

    def check(name):
        for width, height in [(1440, 1000), (375, 812)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.wait_for_timeout(100)
                if name == "form":
                    flag.scroll_into_view_if_needed()
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                for dialog in page.get_by_role("dialog").all():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))"
                )
                assert not violations, (name, width, theme, violations)
                page.screenshot(path=f"/tmp/netrix-gateway-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    row.get_by_role("button", name="192.0.2.10 düzenle", exact=True).click()
    flag = page.get_by_role("checkbox", name="Gateway olarak işaretle", exact=True)
    expect(flag).not_to_be_checked()
    flag.check()
    check("form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(address).to_have_class(re.compile("ipam-gateway"))
    expect(row.get_by_text("Gateway", exact=True)).to_be_visible()
    expect(address).to_have_css("color", "rgb(74, 222, 128)")
    address.click()
    expect(page.get_by_role("dialog").get_by_text("Evet", exact=True)).to_have_class("ipam-gateway")
    check("detail")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    check("table")
    page.reload()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(address).to_have_class(re.compile("ipam-gateway"))
    row.get_by_role("button", name="192.0.2.10 düzenle", exact=True).click()
    expect(flag).to_be_checked()
    flag.uncheck()
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(address).not_to_have_class(re.compile("ipam-gateway"))
    expect(row.get_by_text("Gateway", exact=True)).to_have_count(0)
    address.click()
    expect(page.get_by_role("dialog").get_by_text("Hayır", exact=True)).to_have_class("ipam-not-gateway")
    expect(page.get_by_role("dialog").get_by_text("Hayır", exact=True)).to_have_css(
        "color", "rgb(185, 28, 28)"
    )
    assert not errors, errors
    browser.close()
print(
    "PASS: gateway save/reload/unset, green IP, Evet/Hayır colors, desktop/mobile, light/dark, accessibility"
)
