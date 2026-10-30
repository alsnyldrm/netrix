"""CSV browser workflow against a disposable local API; no real device access."""

import csv
import io
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8215"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000},
        bypass_csp=True,
        reduced_motion="reduce",
        accept_downloads=True,
    )
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    export = page.get_by_role("button", name="Seçilenleri CSV dışarı aktar", exact=True)
    expect(export).to_be_disabled()
    page.get_by_role("checkbox", name="Fixture 34 seç", exact=True).check()
    page.get_by_role("checkbox", name="Fixture 33 seç", exact=True).check()
    with page.expect_download() as download:
        export.click()
    payload = Path(download.value.path()).read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(payload)))
    assert {row["Cihaz adı"] for row in rows} == {"Fixture 33", "Fixture 34"}
    assert all(row["SSH parolası"] == "********" for row in rows)
    assert "fixture-password" not in payload

    def screen(name):
        for theme in ("light", "dark"):
            for width, height in ((1440, 1000), (375, 812)):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                if page.get_by_role("dialog").count():
                    assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                result = page.evaluate(
                    "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
                )
                reports[f"{name}-{theme}-{width}"] = [v["id"] for v in result["violations"]]
                page.screenshot(path=f"artifacts/device-csv-{name}-{theme}-{width}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    screen("toolbar")
    page.get_by_role("button", name="CSV içeri aktar", exact=True).click()
    with page.expect_download() as template:
        page.get_by_role("button", name="CSV şablonu indir", exact=True).click()
    assert "Cihaz adı" in Path(template.value.path()).read_text(encoding="utf-8-sig")
    file_input = page.get_by_label("CSV dosyası", exact=True)
    file_input.set_input_files(
        {
            "name": "bad.csv",
            "mimeType": "text/csv",
            "buffer": b"name,management_ip,vrf_id\nBroken,invalid,Global",
        }
    )
    expect(page.locator(".csv-summary")).to_contain_text("1 hatalı satır")
    expect(page.get_by_role("button", name="İçeri aktar", exact=True)).to_be_disabled()
    screen("errors")
    content = "Cihaz adı;Yönetim IP adresi;VRF;Lokasyon;SSH / API profili;SSH parolası\nCSV cihaz A;192.0.2.101;Global;Kuzey Kampüs;Fixture SSH;********\nCSV cihaz B;192.0.2.102;Global;Kuzey Kampüs;Fixture SSH;********\n"
    file_input.set_input_files(
        {"name": "devices.csv", "mimeType": "text/csv", "buffer": content.encode("utf-8")}
    )
    expect(page.locator(".csv-summary")).to_contain_text("2 geçerli")
    screen("preview")
    page.get_by_role("button", name="2 cihazı içeri aktar", exact=True).click()
    expect(page.locator(".csv-summary")).to_have_text("2 cihaz içeri aktarıldı.")
    page.get_by_role("button", name="Kapat", exact=True).click()
    search = page.get_by_role("textbox", name="Kayıtlarda ara", exact=True)
    search.fill("CSV cihaz")
    expect(page.locator(".inventory-pagination")).to_contain_text("2 kayıt")
    page.get_by_role("button", name="CSV içeri aktar", exact=True).click()
    file_input.set_input_files(
        {"name": "devices.csv", "mimeType": "text/csv", "buffer": content.encode("utf-8")}
    )
    expect(page.locator(".csv-summary")).to_contain_text("2 hatalı satır")
    expect(page.get_by_role("button", name="İçeri aktar", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(
        json.dumps(
            {
                "csv_workflow": "PASS",
                "selected_only": True,
                "masked_secrets": True,
                "import_preview_atomic": True,
                "duplicate_rejection": True,
                "axe": reports,
                "console_errors": errors,
            }
        )
    )
    browser.close()
