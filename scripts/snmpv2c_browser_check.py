"""Vault create/update, profile selection, keyboard, responsive layout and axe checks.

Run against scripts.inventory_fixture on a disposable local DB; no workers run.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8216")
PROFILE = "Browser SNMPv2c " + uuid4().hex[:8]
assert BASE.startswith("http://127.0.0.1:")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, saves = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.on(
        "request",
        lambda request: (
            saves.append(request.post_data_json)
            if "/api/v1/credentials" in request.url and request.method in ("POST", "PUT")
            else None
        ),
    )
    page.goto(BASE + "/#credentials")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    protocol = page.get_by_role("combobox", name="Protokol", exact=True)
    expect(protocol).to_have_value("snmpv3")
    protocol.select_option("snmpv2c")
    community = page.get_by_label("SNMP community", exact=False)
    expect(community).to_have_attribute("type", "password")
    expect(community).to_have_attribute("required", "")
    expect(page.get_by_label("Kullanıcı adı", exact=True)).to_have_count(0)
    page.get_by_label("Profil adı", exact=False).fill(PROFILE)
    community.fill("browser-fixture-community")
    # Changing protocol must not submit hidden secrets from another protocol.
    protocol.select_option("snmpv3")
    page.get_by_label("SNMP auth anahtarı", exact=False).fill("unused-fixture")
    protocol.select_option("snmpv2c")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert saves[-1]["secret"] == {"community": "browser-fixture-community"}
    row = page.get_by_role("row").filter(has_text=PROFILE)
    expect(row).to_contain_text("SNMPv2c")
    row.get_by_role("button", name="Kaydı düzenle", exact=True).click()
    expect(community).to_have_value("")
    community.fill("browser-rotated-community")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert saves[-1]["secret"] == {"community": "browser-rotated-community"}
    reports = {}
    Path("artifacts").mkdir(exist_ok=True)
    for theme, width, height in [
        ("light", 1440, 1000),
        ("dark", 1440, 1000),
        ("light", 375, 812),
        ("dark", 812, 375),
    ]:
        page.evaluate("t => document.documentElement.dataset.theme = t", theme)
        page.set_viewport_size({"width": width, "height": height})
        page.get_by_role("button", name="Yeni kayıt", exact=True).click()
        protocol.select_option("snmpv2c")
        community.focus()
        community.press("Tab")
        dialog = page.get_by_role("dialog")
        assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
        fields = page.locator(".form-field").evaluate_all("""els=>els.map(e=>{
            const r=x=>{const b=x.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}};
            return {field:r(e),label:r(e.querySelector('.field-title')),control:r(e.querySelector('input,select'))};
        })""")
        assert len(fields) == 3
        for field in fields:
            assert abs(field["label"]["x"] - field["control"]["x"]) <= 1
            assert abs(field["field"]["w"] - field["control"]["w"]) <= 1
        if width > 760:
            assert abs(fields[0]["control"]["y"] - fields[1]["control"]["y"]) <= 1
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        report = page.evaluate(
            "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
        )
        reports[f"{theme}-{width}"] = [v["id"] for v in report["violations"]]
        page.screenshot(path=f"artifacts/snmpv2c-vault-{theme}-{width}.png", full_page=True)
        page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1440, "height": 1000})
    for section in ("devices", "discovery"):
        page.goto(BASE + "/#" + section)
        page.get_by_role("button", name="Yeni kayıt", exact=True).click()
        label = "SNMP profili" if section == "devices" else "SNMP erişim profili"
        field = page.get_by_label(label, exact=False)
        field.select_option(label=PROFILE)
        expect(field.locator("option:checked")).to_have_text(PROFILE)
        page.keyboard.press("Escape")
    page.goto(BASE + "/#devices")
    page.get_by_role("button", name="Kaydı düzenle", exact=True).first.click()
    page.get_by_label("SNMP profili", exact=False).select_option(label=PROFILE)
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.get_by_role("button", name="Kaydı düzenle", exact=True).first.click()
    page.locator(".device-test-settings button").click()
    expect(page.get_by_role("radio", name="SNMPv2c", exact=True)).to_be_enabled()
    expect(page.get_by_role("radio", name="SNMPv3", exact=True)).to_be_disabled()
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        dialog = page.get_by_role("dialog").last
        expect(dialog).to_contain_text("UDP 161")
        assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
        options = page.locator(".connection-test-protocols label").evaluate_all(
            "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
        )
        assert len(options) == 4
        assert max(o["w"] for o in options) - min(o["w"] for o in options) <= 1
        assert max(o["h"] for o in options) - min(o["h"] for o in options) <= 1
        if width == 1440:
            assert abs(options[0]["y"] - options[1]["y"]) <= 1
            assert abs(options[2]["y"] - options[3]["y"]) <= 1
            assert abs(options[0]["x"] - options[2]["x"]) <= 1
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        report = page.evaluate(
            "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
        )
        reports[f"connection-{width}"] = [v["id"] for v in report["violations"]]
        page.screenshot(path=f"artifacts/snmpv2c-connection-{width}.png", full_page=True)
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {"vault_create_rotate": "PASS", "profile_selection": "PASS", "alignment": "PASS", "axe": reports}
        )
    )
    browser.close()
