"""Desktop/mobile UI, real API file upload, grouping, ordering and performance; fixture only."""

import hashlib
import json
import statistics
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8231"
content = b"firmware browser fixture\x00\xff" * 100
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    errors = []
    reports = {}
    durations = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#firmware-devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.locator(".fw-workspace tbody tr")).to_have_count(50)
    assert "1000 kayıt" in page.locator(".fw-pager").inner_text()
    nav_groups = page.locator(".nav-group-toggle").all_text_contents()
    if nav_groups:
        assert nav_groups.index("Firmware") == nav_groups.index("IP adres yönetimi") + 1, nav_groups

    def check(name):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
        )
        page.screenshot(path=f"artifacts/firmware-{name}.png", full_page=True)

    tabs = {
        "devices": "Cihazlar",
        "images": "Firmware deposu",
        "groups": "Gruplar",
        "plans": "Güncelleme planları",
        "history": "İşlem geçmişi",
        "service": "Aktarım ve kurtarma",
    }
    firmware_menu = page.locator(".nav-group").filter(
        has=page.get_by_role("button", name="Firmware", exact=True)
    )
    for width, theme in ((1440, "light"), (1440, "dark"), (375, "light"), (375, "dark")):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        for tab in tabs:
            start = time.perf_counter()
            if width < 1024:
                page.get_by_role("button", name="Menüyü aç", exact=True).click()
            group_button = firmware_menu.get_by_role("button", name="Firmware", exact=True)
            if group_button.get_attribute("aria-expanded") != "true":
                group_button.click()
            firmware_menu.get_by_role("button", name=tabs[tab], exact=True).click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name=tabs[tab], exact=True).first).to_be_visible()
            expect(firmware_menu.locator('.nav-item[aria-current="page"]')).to_have_text(tabs[tab])
            expect(page.locator("main nav")).to_have_count(0)
            if width < 1024:
                expect(page.locator(".sidebar")).not_to_be_visible()
            durations.append((time.perf_counter() - start) * 1000)
            check(f"{tab}-{width}-{theme}")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(BASE + "/#firmware-images")
    page.get_by_role("button", name="Dosya yükle", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Dosya adı için açıklama").fill("Aruba fixture image")
    dialog.get_by_label("Hedef sürüm", exact=True).fill("WC.16.11.0026")
    dialog.get_by_label("Uyumlu ürün kodları / tam modeller").fill("JL256A")
    dialog.get_by_label("Üreticinin yayımladığı SHA-256").fill(hashlib.sha256(content).hexdigest())
    dialog.get_by_label("Firmware dosyası", exact=True).set_input_files(
        {"name": "fixture.swi", "mimeType": "application/octet-stream", "buffer": content}
    )
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        check(f"image-form-{width}")
    page.set_viewport_size({"width": 1440, "height": 1000})
    dialog.get_by_role("button", name="Dosyayı yükle", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page.locator(".fw-workspace tbody")).to_contain_text("Aruba fixture image")
    for name, index in (("Role A", 0), ("Role B", 1)):
        page.goto(BASE + "/#firmware-groups")
        page.get_by_role("button", name="Grup oluştur", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Grup adı", exact=True).fill(name)
        dialog.locator(".fw-checklist input").nth(index).check()
        for width in (1440, 375):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
            check(f"group-form-{name[-1]}-{width}")
        page.set_viewport_size({"width": 1440, "height": 1000})
        dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
        expect(dialog).to_have_count(0)
        expect(page.locator(".fw-workspace tbody")).to_contain_text(name)
    page.goto(BASE + "/#firmware-plans")
    page.get_by_role("button", name="Plan oluştur", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Plan adı", exact=True).fill("User-defined order")
    dialog.get_by_label("Firmware grubu", exact=True).select_option(label="Role A · 1 cihaz")
    dialog.get_by_label("Firmware imajı", exact=True).select_option(index=1)
    dialog.get_by_role("button", name="Aşama ekle", exact=True).click()
    dialog.get_by_label("Firmware grubu", exact=True).nth(1).select_option(label="Role B · 1 cihaz")
    dialog.get_by_label("Firmware imajı", exact=True).nth(1).select_option(index=1)
    dialog.get_by_role("button", name="Aşama 2 yukarı", exact=True).click()
    assert (
        "Role B"
        in dialog.get_by_label("Firmware grubu", exact=True).first.locator("option:checked").inner_text()
    )
    dialog.get_by_label("İşlem", exact=True).select_option("upgrade")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        check(f"upgrade-form-{width}")
    dialog.get_by_label("İşlem", exact=True).select_option("check")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        check(f"plan-form-{width}")
        bounds = dialog.locator(".fw-form-actions button").evaluate_all(
            "els=>els.map(e=>{const r=e.getBoundingClientRect();return {y:r.y,h:r.height,w:r.width}})"
        )
        assert abs(bounds[0]["y"] - bounds[1]["y"]) < 1 and abs(bounds[0]["h"] - bounds[1]["h"]) < 1, bounds
        if width == 375:
            assert abs(bounds[0]["w"] - bounds[1]["w"]) < 1, bounds
    dialog.get_by_role("button", name="Taslak oluştur", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("Taslak", exact=True)).to_be_visible()
    assert page.get_by_role("dialog").locator(".fw-plan-order b").all_text_contents() == ["Role B", "Role A"]
    check("plan-detail-mobile")
    page.get_by_role("dialog").get_by_role("button", name="Başlat", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="İşlemi onayla", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("Sırada", exact=True).first).to_be_visible()
    # No worker is running: the explicit user trigger queues an action, never a fixture scan.
    page.get_by_role("dialog").get_by_role("button", name="Sonraki işlemleri durdur", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="İşlemi onayla", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("Durduruldu", exact=True).first).to_be_visible()
    page.keyboard.press("Escape")
    measurements = page.evaluate(
        """async()=>{const paths=['/firmware/overview','/firmware/devices?limit=50','/firmware/images','/firmware/groups','/firmware/plans'];const r=[];for(let i=0;i<20;i++){const p=paths[i%paths.length],t=performance.now();const x=await fetch('/api/v1'+p);if(!x.ok)throw Error(p);await x.json();r.push(performance.now()-t)}return r}"""
    )
    assert not errors, errors
    assert not any(reports.values()), reports
    assert max(measurements) < 500, measurements
    print(
        json.dumps(
            {
                "views": len(reports),
                "axe": reports,
                "page_errors": errors,
                "api_ms_median": round(statistics.median(measurements), 2),
                "api_ms_p95": round(sorted(measurements)[18], 2),
                "navigation_ms_median": round(statistics.median(durations), 2),
                "records": 1000,
            }
        )
    )
    browser.close()
