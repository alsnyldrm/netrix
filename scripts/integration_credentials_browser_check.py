"""Saved integration credentials survive form edits; local API fixture only."""

import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8228")
assert BASE.startswith("http://127.0.0.1:")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, saves, reports = [], [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.on(
        "request",
        lambda request: (
            saves.append(request.post_data_json)
            if "/api/v1/integrations" in request.url and request.method in ("POST", "PUT")
            else None
        ),
    )
    page.goto(BASE + "/#integrations")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Entegrasyon ekle", exact=True).click()
    name = "DHCP " + uuid4().hex[:8]
    page.get_by_label("Entegrasyon adı", exact=True).fill(name)
    page.get_by_role("combobox", name="Entegrasyon türü", exact=True).select_option("windows_dhcp")
    page.get_by_label("Sunucu adı veya IP", exact=True).fill("dhcp.example.test")
    username = page.get_by_label("Kullanıcı", exact=True)
    password = page.get_by_label("Parola", exact=True)
    expect(username).to_have_attribute("required", "")
    expect(password).to_have_attribute("required", "")
    username.fill("EXAMPLE\\reader")
    password.fill("fixture-only-password")
    page.get_by_role("button", name="Entegrasyonu kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    change = page.get_by_role("checkbox", name="Kullanıcı/parolayı değiştir", exact=True)
    save = page.get_by_role("button", name="Entegrasyonu kaydet", exact=True)
    for integration in (name, "Kampüs vCenter"):
        page.get_by_role("button", name=integration + " düzenle", exact=True).click()
        expect(change).not_to_be_checked()
        expect(username).to_have_count(0)
        expect(password).to_have_count(0)
        expect(page.get_by_role("dialog")).to_contain_text("Kayıtlı kullanıcı ve parola korunacak")
        page.get_by_label("Eşitleme aralığı (sn; 0 = manuel)", exact=True).fill("120")
        save.click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert saves[-1]["username"] == saves[-1]["password"] == ""
        page.get_by_role("button", name=integration + " düzenle", exact=True).click()
        expect(change).not_to_be_checked()
        change.focus()
        change.press("Space")
        expect(username).to_have_value("")
        expect(password).to_have_value("")
        username.fill("replacement")
        count = len(saves)
        save.click()
        expect(password).to_be_focused()
        assert len(saves) == count, "Partial replacement must be stopped before submission"
        password.fill("fixture-rotated-password")
        save.click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert saves[-1]["username"] == "replacement" and saves[-1]["password"] == "fixture-rotated-password"
        page.get_by_role("button", name=integration + " düzenle", exact=True).click()
        expect(change).not_to_be_checked()
        change.check()
        username.fill("discarded-replacement")
        password.fill("discarded-password")
        change.uncheck()
        expect(password).to_have_count(0)
        save.click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert saves[-1]["username"] == saves[-1]["password"] == ""
    page.get_by_role("button", name="Kampüs vCenter düzenle", exact=True).click()
    host = page.get_by_label("Sunucu adı veya IP", exact=True)
    host.fill("another.example.test")
    expect(change).to_be_checked()
    expect(change).to_be_disabled()
    expect(username).to_have_attribute("required", "")
    expect(password).to_have_attribute("required", "")
    host.fill("vc.example.test")
    expect(change).not_to_be_checked()
    expect(username).to_have_count(0)
    expect(password).to_have_count(0)
    Path("artifacts").mkdir(exist_ok=True)
    for mode in ("saved", "replace"):
        change.set_checked(mode == "replace")
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                dialog = page.get_by_role("dialog")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                fields = dialog.locator(".ipam-field").evaluate_all("""els=>els.map(e=>{
                    const rect=x=>{const r=x.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}};
                    return {label:rect(e.querySelector('span')), control:rect(e.querySelector('input,select'))};
                })""")
                for field in fields:
                    assert abs(field["label"]["x"] - field["control"]["x"]) <= 1
                assert max(f["control"]["h"] for f in fields) - min(f["control"]["h"] for f in fields) <= 1
                for left, right in zip(fields, fields[1:]):
                    if abs(left["label"]["y"] - right["label"]["y"]) <= 1:
                        assert abs(left["control"]["y"] - right["control"]["y"]) <= 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                report = page.evaluate(
                    "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
                )
                key = f"{mode}-{theme}-{width}"
                reports[key] = [v["id"] for v in report["violations"]]
                page.screenshot(path=f"artifacts/integration-credentials-{key}.png", full_page=False)
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {
                "create_required": "PASS",
                "settings_without_credentials": "PASS",
                "replace_and_discard": "PASS",
                "changed_host_requires_credentials": "PASS",
                "alignment": "PASS",
                "axe": reports,
            }
        )
    )
    browser.close()
