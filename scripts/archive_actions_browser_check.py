"""Archive actions on disposable fixture records only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8242")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda s: None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base)
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    # Prepare archived fixtures through the same API as the UI; never real inventory.
    data = page.request.get(base + "/api/v1/devices?limit=100").json()["items"]
    ids = [d["id"] for d in data[:3]]
    response = page.request.post(
        base + "/api/v1/inventory/devices/bulk",
        data={"ids": ids, "action": "delete"},
        headers={"x-netrix-request": "1"},
    )
    assert response.ok, response.text()
    page.goto(base + "/#archived-devices")
    page.reload()
    page.wait_for_load_state("networkidle")
    toolbar = page.locator(".inventory-selection")
    expect(toolbar.get_by_role("button", name="Toplu geri yükle", exact=True)).to_be_disabled()
    expect(toolbar.get_by_role("button", name="Kalıcı sil", exact=True)).to_be_disabled()
    Path("artifacts").mkdir(exist_ok=True)
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        boxes = toolbar.locator("button").evaluate_all(
            "els=>els.map(e=>{let r=e.getBoundingClientRect();return {y:r.y,h:r.height}})"
        )
        assert all(b["h"] >= 44 for b in boxes)
        if width == 1440:
            assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 1
        page.screenshot(path=f"artifacts/archive-actions-list-{width}.png", full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("checkbox", name="Bu sayfadaki kayıtları seç", exact=True).check()
    toolbar.get_by_role("button", name="Toplu geri yükle", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("3 cihaz")
    page.get_by_role("dialog").get_by_role("button", name="Geri yükle", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    response = page.request.post(
        base + "/api/v1/inventory/devices/bulk",
        data={"ids": ids, "action": "delete"},
        headers={"x-netrix-request": "1"},
    )
    assert response.ok
    page.reload()
    page.wait_for_load_state("networkidle")
    # Single-row purge confirmation, cancellation and no premature deletion.
    page.get_by_role("button", name=data[0]["name"] + " kalıcı sil", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("1 cihaz kalıcı silinecek")
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("3 kayıt")
    page.get_by_role("checkbox", name="Bu sayfadaki kayıtları seç", exact=True).check()
    toolbar.get_by_role("button", name="Kalıcı sil", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("3 cihaz kalıcı silinecek")
    reports = {}
    Path("artifacts").mkdir(exist_ok=True)
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            boxes = dialog.locator(".dialog-footer button").evaluate_all(
                "els=>els.map(e=>{let r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
            )
            axis = "x" if width <= 640 else "y"
            assert abs(boxes[0][axis] - boxes[1][axis]) < 1
            assert all(b["h"] >= 44 for b in boxes), (width, theme, boxes)
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/archive-purge-{width}-{theme}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    dialog.get_by_role("button", name="3 cihazı kalıcı sil", exact=True).click()
    expect(page.locator(".inventory-pagination")).to_contain_text("0 kayıt")
    assert all(page.request.get(base + "/api/v1/devices/" + id).status == 404 for id in ids)
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"archive_actions": "PASS", "axe": reports, "errors": errors}))
    browser.close()
