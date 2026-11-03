"""Real-backend checks for manual display, searchable locations and persisted selection."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8224"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    user = page.request.get(BASE + "/api/v1/auth/me").json()
    page.evaluate(
        "id=>{localStorage.setItem(`netrix.ipam.columns.${id}`,JSON.stringify(['address','hostname','mac_address','connected_device','connected_port']));localStorage.removeItem(`netrix.ipam.columns.${id}.v2`)}",
        user["id"],
    )
    page.reload()
    page.wait_for_load_state("networkidle")
    page.screenshot(path="/tmp/netrix-manual-list-diagnostic.png", full_page=True)
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(page.get_by_role("cell", name="MANUAL-FW-11", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="MANUAL-FW-12", exact=True)).to_be_visible()
    expect(page.get_by_role("columnheader", name="İşletim sistemi", exact=True)).to_be_visible()
    expect(page.get_by_role("columnheader", name="Kabinet no", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Switch 1 Manuel", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="1/1/7 Manuel", exact=True)).to_be_visible()
    page.get_by_role("button", name="192.0.2.11", exact=True).click()
    detail_dialog = page.get_by_role("dialog")
    table = detail_dialog.get_by_role("table", name="Kabinet yerleşimi", exact=True)
    expect(table.get_by_role("row").nth(1).get_by_role("cell")).to_have_text(
        ["FBU-F", "L-0", "A", "Sunucu Odası", "02", "—"]
    )
    expect(detail_dialog.get_by_text("Manuel konum bilgisi", exact=False)).to_be_visible()
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            table.scroll_into_view_if_needed()
            assert detail_dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"/tmp/netrix-manual-detail-{width}-{theme}.png")
    detail_dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    # A user's new column choices persist, but saving metadata reveals its columns immediately.
    page.get_by_role("button", name="Sütunlar", exact=True).click()
    columns_dialog = page.get_by_role("dialog")
    columns_dialog.get_by_role("checkbox", name="İşletim sistemi", exact=True).uncheck()
    columns_dialog.get_by_role("button", name="Sütunları uygula", exact=True).click()
    expect(page.get_by_role("columnheader", name="İşletim sistemi", exact=True)).to_have_count(0)
    page.reload()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(page.get_by_role("columnheader", name="İşletim sistemi", exact=True)).to_have_count(0)
    page.get_by_role("button", name="192.0.2.11 düzenle", exact=True).click()
    dialog = page.get_by_role("dialog")
    room = dialog.get_by_role("combobox", name="Oda", exact=True)
    cabinet = dialog.get_by_role("combobox", name="Kabinet no", exact=True)
    interface = dialog.get_by_role("combobox", name="Arayüz", exact=True)
    expect(interface.locator("option:checked")).to_have_text("1/1/7")
    expect(room).to_have_value("L-0/A/Sunucu Odası")
    expect(cabinet).to_have_value("FBU-F / L-0/A/Sunucu Odası / Kabin 02")
    room.fill("L-1 B")
    expect(page.get_by_role("listbox").get_by_role("option")).to_have_text(["L-1/B/Elektrik Odası"])
    # Arrow navigation commits a stable room ID; Escape cancels filtering.
    room.press("ArrowDown")
    room.press("Enter")
    expect(cabinet).to_have_value("")
    cabinet.fill("L-1 B 02")
    expect(page.get_by_role("listbox").get_by_role("option")).to_have_text(
        ["FBU-F / L-1/B/Elektrik Odası / Kabin 02"]
    )
    page.get_by_role("listbox").get_by_role("option").click()
    expect(cabinet).to_have_value("FBU-F / L-1/B/Elektrik Odası / Kabin 02")
    expect(cabinet).to_have_attribute("aria-expanded", "false")
    mac = dialog.get_by_role("textbox", name="MAC adresi", exact=True)
    expect(mac).to_have_value("")
    mac.fill("not-a-mac")
    with page.expect_response(
        lambda r: r.request.method == "PUT" and "/api/v1/addresses/" in r.url
    ) as invalid:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert invalid.value.status == 422
    expect(dialog.get_by_role("alert")).to_contain_text("Geçerli bir MAC adresi")
    mac.fill("02-AA-BB-CC-DD-EE")
    expect(dialog.get_by_role("alert")).to_have_count(0)
    dialog.get_by_role("textbox", name="Hostname", exact=True).fill("CHANGED-FW-11")
    dialog.get_by_role("combobox", name="İşletim sistemi", exact=True).select_option("Linux")

    def check(name, popup=False):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("dark", "light"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                cabinet.scroll_into_view_if_needed()
                if popup:
                    cabinet.click()
                    cabinet.fill("02")
                    expect(page.get_by_role("listbox").get_by_role("option")).to_be_visible()
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                # Each row shares its column edges and input baselines.
                boxes = [
                    e.bounding_box()
                    for e in (cabinet, dialog.get_by_role("combobox", name="İşletim sistemi", exact=True))
                ]
                assert abs(boxes[0]["width"] - boxes[1]["width"]) < 1
                controls = [
                    cabinet,
                    room,
                    dialog.get_by_role("combobox", name="İşletim sistemi", exact=True),
                    dialog.locator(".checkbox-control"),
                    mac,
                ]
                heights = [control.bounding_box()["height"] for control in controls]
                assert all(abs(height - 40) < 1 for height in heights), (width, theme, heights)
                if width == 1440:
                    assert abs(mac.bounding_box()["y"] - boxes[1]["y"]) < 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                assert not violations, (name, width, theme, violations)
                page.screenshot(path=f"/tmp/netrix-manual-{name}-{width}-{theme}.png")
                if popup:
                    cabinet.press("Escape")
                    expect(dialog).to_be_visible()
                    expect(cabinet).to_have_value("FBU-F / L-1/B/Elektrik Odası / Kabin 02")
        page.set_viewport_size({"width": 1440, "height": 1000})

    check("editor")
    check("search", popup=True)
    with page.expect_response(
        lambda r: r.request.method == "PUT" and "/api/v1/addresses/" in r.url
    ) as response:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert response.value.ok, response.value.text()
    payload = response.value.request.post_data_json
    assert payload["cabinet"] == "02" and payload["operating_system"] == "Linux"
    assert response.value.json()["mac_address"] == "02:aa:bb:cc:dd:ee"
    row_id = response.value.json()["id"]
    expect(page.get_by_role("cell", name="CHANGED-FW-11", exact=True)).to_be_visible()
    expect(page.get_by_role("columnheader", name="İşletim sistemi", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Linux", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="02:aa:bb:cc:dd:ee", exact=True)).to_be_visible()
    page.get_by_role("button", name="192.0.2.11", exact=True).click()
    saved_location = page.get_by_role("dialog").get_by_role("table", name="Kabinet yerleşimi", exact=True)
    expect(saved_location.get_by_role("row").nth(1).get_by_role("cell")).to_have_text(
        ["FBU-F", "L-1", "B", "Elektrik Odası", "02", "—"]
    )
    page.get_by_role("dialog").get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.reload()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("button", name="192.0.2.11 düzenle", exact=True).click()
    expect(room).to_have_value("L-1/B/Elektrik Odası")
    expect(cabinet).to_have_value("FBU-F / L-1/B/Elektrik Odası / Kabin 02")
    expect(interface.locator("option:checked")).to_have_text("1/1/7")
    expect(mac).to_have_value("02:aa:bb:cc:dd:ee")
    mac.fill("")
    # Clearing manual data restores DNS, while saving an untouched edit must not pin it.
    dialog.get_by_role("textbox", name="Hostname", exact=True).fill("")
    dialog.get_by_role("combobox", name="İşletim sistemi", exact=True).select_option("")
    dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="dns-11.example.test", exact=True)).to_be_visible()
    page.get_by_role("button", name="192.0.2.11 düzenle", exact=True).click()
    expect(dialog.get_by_role("textbox", name="Hostname", exact=True)).to_have_value("")
    dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(dialog).not_to_be_visible()
    item = page.request.get(BASE + f"/api/v1/ipam/addresses/{row_id}").json()
    assert item["managed"]["hostname"] == "" and item["hostname"] == "dns-11.example.test"
    assert item["managed"]["mac_address"] == item["mac_address"] == ""
    # The shared room picker also works in new-cabinet forms, including required validation.
    page.goto(BASE + "/#cabinets")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("textbox", name="Kabinet no", exact=True).fill("99")
    dialog.get_by_role("combobox", name="Lokasyon", exact=True).select_option(label="FBU-F")
    room = dialog.get_by_role("combobox", name="Oda", exact=True)
    assert not room.evaluate("e=>e.checkValidity()")
    room.fill("L-1/A")
    expect(page.get_by_role("listbox").get_by_role("option")).to_have_text(["L-1/A/Elektrik Odası"])
    page.get_by_role("listbox").get_by_role("option").click()
    assert room.evaluate("e=>e.checkValidity()")
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            room.scroll_into_view_if_needed()
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"/tmp/netrix-manual-new-cabinet-{width}-{theme}.png")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/api/v1/cabinets")
    ) as response:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert response.value.ok, response.value.text()
    assert response.value.json()["sub_site_id"]
    assert not errors, errors
    print(
        json.dumps(
            {
                "manual_display": "PASS",
                "duplicate_rooms": "PASS",
                "search_keyboard_save": "PASS",
                "desktop_mobile_axe": "PASS",
            }
        )
    )
    browser.close()
