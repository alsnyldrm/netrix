"""Manual identity edit and inventory backup group bulk assignment on a local API."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8239"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    Path("artifacts").mkdir(exist_ok=True)

    def check(name, focus):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                focus.scroll_into_view_if_needed()
                dialog = page.get_by_role("dialog")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                if name == "bulk":
                    boxes = dialog.locator(
                        ".bulk-field select, .bulk-field input:not([type=checkbox])"
                    ).evaluate_all(
                        "es=>es.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,w:r.width,h:r.height}})"
                    )
                    for axis in ("x", "w", "h"):
                        assert max(b[axis] for b in boxes) - min(b[axis] for b in boxes) <= 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/manual-inventory-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
    search.fill("Fixture 00")
    expect(page.get_by_role("button", name="Kaydı düzenle", exact=True)).to_have_count(1)
    page.get_by_role("button", name="Kaydı düzenle", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text(
        "SNMP ve SSH/API sorguları bu alanların üzerine yazmaz"
    )
    page.get_by_role("textbox", name="Üretici", exact=True).fill("Managed browser vendor")
    check("edit", page.get_by_role("textbox", name="Üretici", exact=True))
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    devices = page.request.get(BASE + "/api/v1/devices").json()["items"]
    device = next(d for d in devices if d["name"] == "Fixture 00")
    assert device["vendor"] == "Managed browser vendor" and device["manual_identity_fields"] == ["vendor"]
    for names in (["Fixture 00"], ["Fixture 00", "Fixture 01"]):
        search.fill("Fixture 0")
        for name in names:
            page.get_by_role("checkbox", name=name + " seç", exact=True).check()
        page.get_by_role("button", name="Toplu değiştir", exact=True).click()
        checkbox = page.get_by_role("checkbox", name="Yedek grubu değiştir", exact=True)
        control = page.get_by_role("combobox", name="Yedek grubu değeri", exact=True)
        expect(control).to_be_disabled()
        checkbox.check()
        control.select_option(label="Firewall")
        if len(names) == 2:
            check("bulk", control)
        page.get_by_role("button", name="Seçilenlere uygula", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        group = page.request.get(BASE + "/api/v1/backup-groups").json()["items"][0]
        devices = page.request.get(BASE + "/api/v1/devices").json()["items"]
        assert all(d["backup_group_id"] == group["id"] for d in devices if d["name"] in names)
        assert next(d for d in devices if d["name"] == "Fixture 02")["backup_group_id"] is None
    for name in ["Fixture 00", "Fixture 01"]:
        page.get_by_role("checkbox", name=name + " seç", exact=True).check()
    page.get_by_role("button", name="Toplu değiştir", exact=True).click()
    page.get_by_role("checkbox", name="Yedek grubu değiştir", exact=True).check()
    page.get_by_role("combobox", name="Yedek grubu değeri", exact=True).select_option("")
    page.get_by_role("button", name="Seçilenlere uygula", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    devices = page.request.get(BASE + "/api/v1/devices").json()["items"]
    assert all(d["backup_group_id"] is None for d in devices if d["name"] in ["Fixture 00", "Fixture 01"])
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"manual_edit_bulk_group": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
