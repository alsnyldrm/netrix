"""Integration test UI against a local API/worker fixture; no real server probes."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8267"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, calls, reports = [], [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "request",
        lambda r: calls.append((r.method, r.url, r.post_data_json if r.method in ("PUT", "POST") else None)),
    )
    page.goto(BASE + "/#integrations")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Kampüs vCenter düzenle", exact=True).click()
    button = page.get_by_role("button", name="Bağlantıyı test et", exact=True)
    expect(page.get_by_label("Parola", exact=True)).to_have_count(0)
    before = len(calls)
    button.click()
    expect(page.get_by_role("button", name="Test ediliyor…", exact=True)).to_be_disabled()
    expect(page.get_by_label("Sunucu adı veya IP", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Entegrasyonu kaydet", exact=True)).to_be_disabled()
    expect(page.locator(".integration-test-result strong")).to_have_text("Bağlantı başarılı")
    tests = [
        body for method, url, body in calls[before:] if url.endswith("/connection-tests") and method == "POST"
    ]
    assert len(tests) == 1 and tests[0]["username"] == tests[0]["password"] == ""
    assert not any(method == "PUT" for method, _, _ in calls[before:])
    host = page.get_by_label("Sunucu adı veya IP", exact=True)
    host.fill("failed.example.test")
    expect(page.locator(".integration-test-result")).to_have_count(0)
    button.click()
    expect(page.get_by_label("Kullanıcı", exact=True)).to_be_focused()
    page.get_by_label("Kullanıcı", exact=True).fill("fixture-replacement")
    page.get_by_label("Parola", exact=True).fill("fixture-secret-replacement")
    button.click()
    expect(page.locator(".integration-test-result strong")).to_have_text("Bağlantı testi tamamlanamadı")
    expect(page.locator(".integration-test-result")).to_contain_text("zaman aşımına")
    assert "Private fixture" not in page.content()
    expect(page.get_by_label("Parola", exact=True)).to_have_value("fixture-secret-replacement")
    host.fill("slow.example.test")
    button.click()
    page.get_by_role("button", name="Testi iptal et", exact=True).click()
    expect(page.locator(".integration-test-result strong")).to_have_text("Test iptal edildi")
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    page.get_by_role("button", name="Kampüs vCenter düzenle", exact=True).click()
    expect(host).to_have_value("vc.example.test")
    change = page.get_by_role("checkbox", name="Kullanıcı/parolayı değiştir", exact=True)
    assert not change.is_checked()
    for mode in ("saved", "replacement"):
        change.set_checked(mode == "replacement")
        if mode == "replacement":
            page.get_by_label("Kullanıcı", exact=True).fill("fixture")
            page.get_by_label("Parola", exact=True).fill("fixture")
        button.click()
        expect(page.locator(".integration-test-result strong")).to_have_text("Bağlantı başarılı")
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                button.scroll_into_view_if_needed()
                dialog = page.get_by_role("dialog")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                fields = dialog.locator(".ipam-field").evaluate_all(
                    "els=>els.map(e=>{const a=e.querySelector('span').getBoundingClientRect(), b=e.querySelector('input,select').getBoundingClientRect(); return {x:a.x,cx:b.x,h:b.height}})"
                )
                assert all(abs(f["x"] - f["cx"]) < 1 for f in fields)
                assert max(f["h"] for f in fields) - min(f["h"] for f in fields) < 1
                buttons = dialog.locator(".integration-form-actions > button").evaluate_all(
                    "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
                )
                assert max(b["h"] for b in buttons) - min(b["h"] for b in buttons) < 1
                for a, b in zip(buttons, buttons[1:]):
                    if abs(a["y"] - b["y"]) < 1:
                        assert b["x"] >= a["x"] + a["w"]
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                key = f"{mode}-{width}-{theme}"
                reports[key] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                page.screenshot(path=f"/tmp/netrix-integration-test-{key}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    page.get_by_role("button", name="Entegrasyon ekle", exact=True).click()
    page.get_by_label("Entegrasyon adı", exact=True).fill("Unsaved DHCP")
    page.get_by_role("combobox", name="Entegrasyon türü", exact=True).select_option("windows_dhcp")
    page.get_by_label("Sunucu adı veya IP", exact=True).fill("dhcp.example.test")
    page.get_by_label("Kullanıcı", exact=True).fill("EXAMPLE\\fixture")
    page.get_by_label("Parola", exact=True).fill("fixture")
    button.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".integration-test-result strong")).to_have_text("Bağlantı başarılı")
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    expect(page.get_by_role("button", name="Unsaved DHCP düzenle", exact=True)).to_have_count(0)
    assert not errors, errors
    assert all(not value for value in reports.values()), reports
    print(
        json.dumps(
            {
                "saved_credentials": "PASS",
                "changed_unsaved_settings": "PASS",
                "failure": "PASS",
                "cancel": "PASS",
                "new_dhcp": "PASS",
                "alignment_and_axe": reports,
            }
        )
    )
    browser.close()
