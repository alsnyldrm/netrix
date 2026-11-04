"""Real form/API: opt-in NIC-Teaming, compact aligned controls and SQL-only save."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8247"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, writes = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: writes.append(r.url) if r.method == "POST" else None)
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("button", name="Yeni IP kaydı", exact=True).click()
    dialog = page.get_by_role("dialog")
    ip = dialog.get_by_role("combobox", name="IP adresi", exact=True)
    ip.fill("192.0.2.13")
    page.get_by_role("option", name="192.0.2.13", exact=True).click()
    nic = dialog.get_by_role("checkbox", name="NIC-Teaming", exact=True)
    expect(nic).not_to_be_checked()
    nic.check()
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            nic.scroll_into_view_if_needed()
            expect(nic).to_be_checked()
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            controls = dialog.locator(".checkbox-control")
            assert controls.count() == 2
            boxes = controls.evaluate_all(
                "es=>es.map(e=>{let r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
            )
            assert all(abs(b["h"] - 40) < 1 for b in boxes)
            if width == 1440:
                assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1
                assert abs(boxes[0]["w"] - boxes[1]["w"]) < 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=>(await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            assert not violations, violations
            page.screenshot(path=f"/tmp/netrix-source-tables-nic-{width}-{theme}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/addresses")
    ) as response:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert response.value.status == 201, response.value.text()
    row = response.value.json()
    assert row["nic_teaming"] is True
    detail = page.request.get(BASE + "/api/v1/ipam/addresses/" + row["id"]).json()
    assert detail["nic_teaming"] is True
    page.get_by_role("button", name="192.0.2.13 IP ayrıntıları", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("NIC-Teaming", exact=True)).to_be_visible()
    assert not any("/scan" in u or "/discover" in u for u in writes), writes
    assert not errors, errors
    browser.close()
print(
    "PASS: NIC-Teaming default/toggle/persistence/details, 40px aligned controls, desktop/mobile themes, WCAG and no source queries"
)
