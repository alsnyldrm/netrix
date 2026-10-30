"""Device type CRUD and connected selectors on the isolated inventory fixture."""

import io
import json
import re
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8205"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    Path("artifacts").mkdir(exist_ok=True)

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                dialog = page.get_by_role("dialog")
                if dialog.count():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                    if name == "type-form":
                        inputs = dialog.locator("input").evaluate_all(
                            "els=>els.map(e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}})"
                        )
                        assert abs(inputs[0]["h"] - inputs[1]["h"]) <= 1
                        if width == 1440:
                            assert abs(inputs[0]["y"] - inputs[1]["y"]) <= 1
                            assert abs(inputs[0]["w"] - inputs[1]["w"]) <= 1
                        else:
                            assert abs(inputs[0]["x"] - inputs[1]["x"]) <= 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/device-types-{name}-{width}-{theme}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    def nav(name):
        page.get_by_role("button", name=name, exact=True).click()

    page.goto(BASE + "/#device-types")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    nav("Çalışma alanına gir")
    expect(page.get_by_role("heading", name="Cihaz Türü", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    group = page.get_by_role("button", name="Envanter", exact=True)
    if group.get_attribute("aria-expanded") == "false":
        group.click()
    labels = page.locator(".nav-item").all_text_contents()
    assert labels.index("Cihaz Türü") == labels.index("Lokasyonlar") + 1
    nav("Yeni kayıt")
    page.get_by_label("Tür adı", exact=False).fill("Controller")
    page.get_by_label("Açıklama", exact=True).fill("Kablosuz denetleyiciler")
    check("type-form")
    nav("Kaydı kaydet")
    expect(page.get_by_role("cell", name="Controller", exact=True)).to_be_visible()
    check("list")
    nav("Cihaz envanteri")
    search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
    search.fill("Fixture 00")
    nav("Kaydı düzenle")
    kinds = page.get_by_role("combobox", name=re.compile("^Cihaz türü"))
    expect(kinds.get_by_role("option", name="Controller", exact=True)).to_have_count(1)
    kinds.select_option(label="Controller")
    check("device-selector")
    nav("Kaydı kaydet")
    expect(page.get_by_role("cell", name="Controller", exact=True)).to_be_visible()
    nav("Cihaz Türü")
    row = page.get_by_role("row").filter(has=page.get_by_role("cell", name="Controller", exact=True))
    row.get_by_role("button", name="Kaydı düzenle", exact=True).click()
    page.get_by_label("Tür adı", exact=False).fill("Kablosuz Denetleyici")
    nav("Kaydı kaydet")
    row = page.get_by_role("row").filter(
        has=page.get_by_role("cell", name="Kablosuz Denetleyici", exact=True)
    )
    row.get_by_role("button", name="Kaydı sil", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Bu türü kullanan cihazlar var")
    nav("Arayüzler")
    search.fill("Kablosuz Denetleyici")
    expect(page.locator(".inventory-pagination")).to_contain_text("1 kayıt")
    nav("Fixture 00 arayüzleri")
    expect(page.get_by_role("cell", name="Kablosuz Denetleyici", exact=True)).to_be_visible()
    nav("Cihaz envanteri")
    search.fill("Fixture 00")
    page.get_by_role("checkbox", name="Fixture 00 seç", exact=True).check()
    nav("Toplu değiştir")
    page.get_by_role("checkbox", name="Cihaz türü değiştir", exact=True).check()
    page.get_by_role("combobox", name="Cihaz türü değeri", exact=True).select_option(label="Switch")
    check("bulk-selector")
    nav("Seçilenlere uygula")
    expect(page.get_by_role("cell", name="Switch", exact=True)).to_be_visible()
    nav("İçeri Aktar")
    page.get_by_role("menuitem", name="XLSX", exact=True).click()
    with page.expect_download() as download:
        nav("XLSX şablonu indir")
    book = load_workbook(io.BytesIO(Path(download.value.path()).read_bytes()))
    values = [
        cell.value
        for sheet, cells in book.defined_names["netrix_kind"].destinations
        for row in book[sheet][cells]
        for cell in row
    ]
    assert "Kablosuz Denetleyici" in values and "Controller" not in values
    page.keyboard.press("Escape")
    nav("Cihaz Türü")
    row = page.get_by_role("row").filter(
        has=page.get_by_role("cell", name="Kablosuz Denetleyici", exact=True)
    )
    row.get_by_role("button", name="Kaydı sil", exact=True).click()
    expect(page.get_by_role("cell", name="Kablosuz Denetleyici", exact=True)).to_have_count(0)
    page.reload()
    expect(page.get_by_role("cell", name="Switch", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Kablosuz Denetleyici", exact=True)).to_have_count(0)
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"device_type_workflows": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
