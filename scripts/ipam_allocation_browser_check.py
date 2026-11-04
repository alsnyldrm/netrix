"""Real API, desktop/mobile alignment, keyboard choices and SQL-only creation."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8247"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: writes.append(request.url) if request.method == "POST" else None)
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading")).to_have_text("Yeni kayıt · VLAN alanları")
    dialog.get_by_role("button", name="Vazgeç", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("button", name="Yeni IP kaydı", exact=True).click()
    expect(dialog.get_by_role("heading")).to_have_text("Yeni kayıt · IP adresleri")
    expect(dialog.get_by_role("combobox", name="VLAN", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("combobox", name="VRF", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("combobox", name="Lokasyon", exact=True).locator("option:checked")).to_have_text("FBU-F")
    address = dialog.get_by_role("combobox", name="IP adresi", exact=True)
    expect(dialog.get_by_text("100 boş IP listeleniyor", exact=True)).to_be_visible()
    address.click()
    options = page.get_by_role("listbox").get_by_role("option")
    for active in ("192.0.2.0", "192.0.2.11", "192.0.2.12", "192.0.2.14", "192.0.2.255"):
        expect(page.get_by_role("option", name=active, exact=True)).to_have_count(0)
    expect(options).to_have_count(100)
    dialog.get_by_role("button", name="Daha fazla IP", exact=True).click()
    expect(dialog.get_by_text("200 boş IP listeleniyor", exact=True)).to_be_visible()
    address.click()
    expect(options).to_have_count(200)
    address.fill("192.0.2.13")
    page.wait_for_load_state("networkidle")
    expect(options).to_have_text(["192.0.2.13"])
    address.press("ArrowDown")
    address.press("Enter")
    expect(address).to_have_value("192.0.2.13")
    address.fill("192.0.2.222")
    dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert not address.evaluate("e=>e.checkValidity()"), "Typed text must be explicitly selected"
    assert len(writes) == 1, writes  # Login only, no stale previous IP assignment.
    address.fill("192.0.2.13")
    page.wait_for_load_state("networkidle")
    address.press("ArrowDown")
    address.press("Enter")
    dialog.get_by_role("textbox", name="Hostname", exact=True).fill("NEW-MANUAL-SERVER")
    dialog.get_by_role("textbox", name="MAC adresi", exact=True).fill("02-AA-BB-CC-DD-13")
    dialog.get_by_role("combobox", name="İşletim sistemi", exact=True).select_option("Linux")
    room = dialog.get_by_role("combobox", name="Oda", exact=True)
    room.fill("L-0 A Sunucu")
    page.get_by_role("option", name="L-0/A/Sunucu Odası", exact=True).click()
    cabinet = dialog.get_by_role("combobox", name="Kabinet no", exact=True)
    cabinet.fill("L-0 A 02")
    page.get_by_role("option", name="FBU-F / L-0/A/Sunucu Odası / Kabin 02", exact=True).click()
    dialog.get_by_role("combobox", name="Bağlı cihaz", exact=True).select_option(label="Switch 1")
    dialog.get_by_role("combobox", name="Arayüz", exact=True).select_option(label="1/1/7")
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            address.scroll_into_view_if_needed()
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            mac = dialog.get_by_role("textbox", name="MAC adresi", exact=True)
            os_field = dialog.get_by_role("combobox", name="İşletim sistemi", exact=True)
            for control in (address, mac, os_field, cabinet, room, dialog.locator(".checkbox-control")):
                assert abs(control.bounding_box()["height"] - 40) < 1
            if width == 1440:
                left, right = address.bounding_box(), dialog.get_by_role("combobox", name="VRF", exact=True).bounding_box()
                assert abs(left["y"] - right["y"]) < 1 and abs(left["width"] - right["width"]) < 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))")
            assert not violations, violations
            page.screenshot(path=f"/tmp/netrix-ip-create-{width}-{theme}.png")
            address.click()
            page.wait_for_load_state("networkidle")
            popup = dialog.locator(".choice-popover")
            popup_rect, frame = popup.bounding_box(), dialog.bounding_box()
            header = dialog.locator(".dialog-header").bounding_box()
            assert popup_rect["y"] >= header["y"] + header["height"] - 1, (width, popup_rect, header)
            assert popup_rect["y"] + popup_rect["height"] <= frame["y"] + frame["height"], (width, popup_rect, frame)
            page.screenshot(path=f"/tmp/netrix-ip-create-options-{width}-{theme}.png")
            address.press("Escape")
    page.set_viewport_size({"width": 1440, "height": 1000})
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/addresses")) as response:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert response.value.status == 201, response.value.text()
    saved = response.value.json()
    assert saved["address"] == "192.0.2.13" and saved["cabinet"] == "02"
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("cell", name="NEW-MANUAL-SERVER", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="02:aa:bb:cc:dd:13", exact=True)).to_be_visible()
    detail = page.request.get(BASE + "/api/v1/ipam/addresses/" + saved["id"]).json()
    assert detail["hostname"] == "NEW-MANUAL-SERVER" and detail["operating_system"] == "Linux"
    assert detail["availability"] == "passive"
    assert len(page.request.get(BASE + "/api/v1/vlans?limit=100").json()["items"]) == 1
    page.get_by_role("button", name="Yeni IP kaydı", exact=True).click()
    address.click()
    address.fill("192.0.2.13")
    page.wait_for_load_state("networkidle")
    expect(options).to_have_count(0)
    dialog.get_by_role("button", name="Vazgeç", exact=True).click()
    page.get_by_role("button", name="VLAN alanlarına dön", exact=True).click()
    expect(page.get_by_role("button", name="Yeni kayıt", exact=True)).to_be_visible()
    assert not any("/scan" in url or "/discover" in url or url.endswith("/vlans") for url in writes), writes
    assert not errors, errors
    browser.close()
    print("PASS: VLAN/list context, paginated vacant IPs, all metadata, desktop/mobile themes, WCAG and SQL-only save")
