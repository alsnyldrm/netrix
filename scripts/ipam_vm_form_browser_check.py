"""VMware attachment shown consistently in both IPAM editors; isolated fixture."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    Path("artifacts").mkdir(exist_ok=True)
    for context in ("prefixes", "addresses"):
        before = next(
            r
            for r in page.request.get("http://127.0.0.1:8211/api/v1/addresses").json()["items"]
            if r["address"] == "192.0.2.10"
        )
        if context == "addresses":
            page.goto("http://127.0.0.1:8211/#addresses")
        page.get_by_role("button", name="192.0.2.10 düzenle", exact=True).click()
        dialog = page.get_by_role("dialog")
        device = dialog.get_by_role("textbox", name="Bağlı cihaz", exact=True)
        interface = dialog.get_by_role("textbox", name="Arayüz", exact=True)
        expect(device).to_have_value("FBU-DS")
        expect(interface).to_have_value("89")
        expect(device).to_have_attribute("readonly", "")
        expect(interface).to_have_attribute("readonly", "")
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("dark", "light"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                interface.scroll_into_view_if_needed()
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                boxes = [c.bounding_box() for c in (device, interface)]
                assert abs(boxes[0]["width"] - boxes[1]["width"]) < 1
                if width == 1440:
                    assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1
                else:
                    assert abs(boxes[0]["x"] - boxes[1]["x"]) < 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                key = f"{context}-{width}-{theme}"
                reports[key] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/vm-form-{key}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})
        dialog.get_by_role("textbox", name="Hostname", exact=True).fill("edited-vm.example.test")
        with page.expect_response(
            lambda r: r.request.method == "PUT" and "/api/v1/addresses/" in r.url
        ) as response:
            dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
        assert response.value.ok, response.value.text()
        payload = response.value.request.post_data_json
        assert payload["device_id"] == before["device_id"]
        assert payload["interface_id"] == before["interface_id"]
        assert "connected_device" not in payload and "connected_port" not in payload
        expect(dialog).not_to_be_visible()
        page.get_by_role("button", name="192.0.2.10 düzenle", exact=True).click()
        expect(page.get_by_role("textbox", name="Bağlı cihaz", exact=True)).to_have_value("FBU-DS")
        expect(page.get_by_role("textbox", name="Arayüz", exact=True)).to_have_value("89")
        page.get_by_role("button", name="Vazgeç", exact=True).click()
    # Physical connections continue to offer filtered inventory controls.
    page.get_by_role("button", name="192.0.2.65 düzenle", exact=True).click()
    expect(page.get_by_role("combobox", name="Bağlı cihaz", exact=True)).to_be_visible()
    expect(page.get_by_role("combobox", name="Arayüz", exact=True)).to_be_visible()
    assert not errors and not any(reports.values()), (errors, reports)
    print(
        json.dumps({"vm_form": "PASS", "save_preserves_assignment": True, "axe": reports, "errors": errors})
    )
    browser.close()
