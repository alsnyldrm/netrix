"""Create cabinets in the open room, and retain the complete form at the root."""

import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, saved = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "request",
        lambda r: (
            saved.append(r.post_data_json)
            if r.method == "POST" and r.url.endswith("/api/v1/cabinets")
            else None
        ),
    )
    page.goto("http://127.0.0.1:8218/#cabinets")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name=re.compile("^Kuzey Kampüs ")).click()
    page.get_by_role("button", name="Arşiv Odası", exact=True).click()
    expect(page.get_by_text("Bu odada henüz kabinet yok.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    form = page.get_by_role("dialog")
    expect(form.get_by_role("combobox")).to_have_count(0)
    expect(form.get_by_role("textbox")).to_have_count(2)
    expect(form.get_by_role("spinbutton")).to_have_count(1)
    context = form.get_by_role("note", name="Kabinetin ekleneceği oda", exact=True)
    expect(context).to_contain_text("Arşiv Odası")
    expect(context).to_contain_text("Kuzey Kampüs")
    expect(context).to_contain_text("Kat: L-0")
    expect(context).to_contain_text("Bölüm: B")

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.wait_for_timeout(350)
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                assert form.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                issues = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                assert not issues, (name, width, theme, issues)
                page.screenshot(path=f"/tmp/netrix-cabinet-create-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    form.get_by_label("Kabinet no", exact=False).fill("5")
    form.get_by_label("Kapasite (U)", exact=False).fill("24")
    form.get_by_label("Açıklama", exact=True).fill("B bölümü kabineti")
    check("room")
    form.get_by_role("button", name="Kaydı kaydet", exact=False).click()
    expect(form).to_have_count(0)
    expect(page.get_by_role("button", name="5", exact=True)).to_be_visible()
    sites = page.request.get("http://127.0.0.1:8218/api/v1/sites?limit=100").json()["items"]
    archive = next(s for s in sites if s["name"] == "Arşiv Odası")
    assert saved[-1] == {
        "name": "5",
        "site_id": archive["parent_id"],
        "sub_site_id": archive["id"],
        "units": 24,
        "description": "B bölümü kabineti",
    }
    page.get_by_role("button", name="Lokasyonlar", exact=True).click()
    page.get_by_role("button", name="Sunucu Odası", exact=True).click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    expect(context).to_contain_text("Sunucu Odası")
    expect(context).to_contain_text("Bölüm: A")
    expect(form.get_by_label("Kabinet no", exact=False)).to_have_value("")
    expect(form.get_by_role("combobox")).to_have_count(0)
    form.get_by_label("Kabinet no", exact=False).fill("5")
    form.get_by_role("button", name="Kaydı kaydet", exact=False).click()
    expect(form).to_have_count(0)
    server = next(s for s in sites if s["name"] == "Sunucu Odası")
    assert saved[-1]["sub_site_id"] == server["id"]
    page.get_by_role("button", name="5 düzenle", exact=True).click()
    expect(form.get_by_role("combobox")).to_have_count(2)
    expect(form.get_by_label("Oda", exact=False)).to_have_value(server["id"])
    expect(form.get_by_label("Oda", exact=False).locator("option:checked")).to_have_text("L-0/A/Sunucu Odası")
    form.get_by_role("button", name="Vazgeç", exact=True).click()
    page.get_by_role("button", name="Lokasyonlar", exact=True).click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    expect(form.get_by_role("combobox")).to_have_count(2)
    expect(form.get_by_label("Lokasyon", exact=False)).to_have_value("")
    expect(form.get_by_label("Oda", exact=False)).to_have_value("")
    expect(context).to_have_count(0)
    check("root")
    form.get_by_label("Lokasyon", exact=False).select_option(label="Güney Kampüs")
    form.get_by_label("Oda", exact=False).select_option(label="L-0/A/Elektrik Odası")
    form.get_by_label("Kabinet no", exact=False).fill("6")
    form.get_by_role("button", name="Kaydı kaydet", exact=False).click()
    expect(form).to_have_count(0)
    electrical = next(s for s in sites if s["name"] == "Elektrik Odası")
    assert saved[-1]["site_id"] == electrical["parent_id"] and saved[-1]["sub_site_id"] == electrical["id"]
    page.get_by_role("button", name="Sunucu Odası", exact=True).click()
    page.evaluate("location.hash='sites'")
    expect(page.get_by_role("heading", name="Lokasyon", exact=True)).to_be_visible()
    page.evaluate("location.hash='cabinets'")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    expect(form.get_by_role("combobox")).to_have_count(2)
    expect(context).to_have_count(0)
    form.get_by_role("button", name="Vazgeç", exact=True).click()
    # Identical room names must remain distinguishable and retain their own IDs.
    added = {}
    for floor, department in [("L-0", "A"), ("L-0", "B"), ("L-1", "A")]:
        response = page.request.post(
            "http://127.0.0.1:8218/api/v1/sites",
            headers={"X-Netrix-Request": "1"},
            data={
                "name": "Elektrik Odası",
                "parent_id": server["parent_id"],
                "institution_id": server["institution_id"],
                "floor_number": floor,
                "department_name": department,
            },
        )
        assert response.status == 201, response.text()
        added[f"{floor}/{department}/Elektrik Odası"] = response.json()["id"]
    page.reload()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    form.get_by_label("Lokasyon", exact=False).select_option(label="Kuzey Kampüs")
    room = form.get_by_label("Oda", exact=False)
    for label, room_id in added.items():
        expect(room.locator(f'option[value="{room_id}"]')).to_have_text(label)
    room.select_option(label="L-1/A/Elektrik Odası")
    form.get_by_label("Kabinet no", exact=False).fill("7")
    check("room-labels")
    form.get_by_role("button", name="Kaydı kaydet", exact=False).click()
    expect(form).to_have_count(0)
    assert saved[-1]["sub_site_id"] == added["L-1/A/Elektrik Odası"]
    assert not errors, errors
    browser.close()
print(
    "PASS: contextual room creation, correct room/site POST, root full form, editing, navigation reset, desktop/mobile, themes and accessibility"
)
