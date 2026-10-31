"""Verify rack placement metadata in the existing IPAM table using an isolated fixture."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8211"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).wait_for()
    prefix = page.request.get(BASE + "/api/v1/prefixes").json()["items"][0]
    site = page.request.get(BASE + "/api/v1/sites").json()["items"][0]
    headers = {"X-Netrix-Request": "1"}

    def write(method, path, data):
        response = page.request.fetch(BASE + "/api/v1/" + path, method=method, data=data, headers=headers)
        assert response.ok, response.text()
        return response.json()

    cabinet = write("POST", "cabinets", {"name": "Room 02", "site_id": site["id"], "units": 42})
    for i in range(11, 14):
        address = f"192.0.2.{i}"
        device = write(
            "POST",
            "devices",
            {"name": f"Rack device {i}", "management_ip": address, "vrf_id": prefix["vrf_id"]},
        )
        write(
            "PUT",
            f"ipam/cabinets/{cabinet['id']}/placements",
            {"device_id": device["id"], "start_unit": i, "units": 1},
        )
    page.reload()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    page.get_by_role("checkbox", name="Yalnızca aktif IP’ler", exact=True).uncheck()
    page.get_by_placeholder("Tüm alanlarda ara…").fill("Room 02")
    cells = page.get_by_role("cell", name="Room 02", exact=True)
    expect(cells).to_have_count(3)
    for i in range(11, 14):
        row = page.get_by_role("row").filter(
            has=page.get_by_role("checkbox", name=f"192.0.2.{i} seç", exact=True)
        )
        expect(row.get_by_role("cell", name="Room 02", exact=True)).to_be_attached()
    for width, height in ((1440, 1000), (375, 812)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            cells.first.scroll_into_view_if_needed()
            expect(cells.first).to_be_visible()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            page.evaluate(Path("frontend/node_modules/axe-core/axe.min.js").read_text())
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/rack-ipam-{width}-{theme}.png")
    assert not errors and not any(reports.values()), (errors, reports)
    print(json.dumps({"three_rack_devices_in_ipam": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
