"""VMware cabinet label is consistent in lists, details and editing."""

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
    expect(row.get_by_role("cell", name="Sanal", exact=True)).to_be_visible()

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                if name == "form":
                    page.get_by_role("textbox", name="Kabinet no", exact=True).scroll_into_view_if_needed()
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                for modal in page.get_by_role("dialog").all():
                    assert modal.evaluate("e=>e.scrollWidth<=e.clientWidth")
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id)"
                )
                assert not violations, (name, width, theme, violations)
                page.screenshot(path=f"/tmp/netrix-virtual-cabinet-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    check("table")
    row.get_by_role("button", name="192.0.2.10", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("Sanal", exact=True)).to_be_visible()
    check("detail")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    row.get_by_role("button", name="192.0.2.10 düzenle", exact=True).click()
    cabinet = page.get_by_role("textbox", name="Kabinet no", exact=True)
    expect(cabinet).to_have_value("Sanal")
    expect(cabinet).to_have_attribute("readonly", "")
    check("form")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(row.get_by_role("cell", name="Sanal", exact=True)).to_be_visible()
    vlan = page.request.get("http://127.0.0.1:8215/api/v1/vlans").json()["items"][0]
    result = page.request.get(
        f"http://127.0.0.1:8215/api/v1/ipam/vlans/{vlan['id']}/addresses?allocated=true"
    ).json()
    vm = next(r for r in result["items"] if r["address"] == "192.0.2.10")
    assert vm["cabinet"] == "Sanal" and vm["managed"]["cabinet"] == ""
    assert not errors, errors
    browser.close()
print(
    "PASS: Sanal in table/detail/read-only editor; managed cabinet preserved; desktop/mobile and accessibility"
)
