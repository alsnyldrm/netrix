"""HP 1950 selectors and encrypted-profile form on a disposable local API."""

import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, reports, writes = [], {}, []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.on(
        "request",
        lambda r: (
            writes.append(r.post_data_json) if r.method == "POST" and r.url.endswith("/credentials") else None
        ),
    )
    Path("artifacts").mkdir(exist_ok=True)

    def check(name, focus_label):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.get_by_label(focus_label, exact=False).scroll_into_view_if_needed()
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                dialog = page.get_by_role("dialog")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                controls = dialog.locator(
                    ".form-field input:not([type=checkbox]), .form-field select"
                ).evaluate_all(
                    "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,row:e.closest('.form-field').getBoundingClientRect().y}})"
                )
                assert max(e["h"] for e in controls) - min(e["h"] for e in controls) <= 1
                assert max(e["w"] for e in controls) - min(e["w"] for e in controls) <= 1
                if width == 375:
                    assert max(e["x"] for e in controls) - min(e["x"] for e in controls) <= 1
                else:
                    for a in controls:
                        for b in controls:
                            if abs(a["row"] - b["row"]) <= 1:
                                assert abs(a["y"] - b["y"]) <= 1, (a, b)
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/hp1950-{name}-{width}-{theme}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto("http://127.0.0.1:8237/#credentials")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    page.get_by_label("Profil adı", exact=False).fill("HP 1950 SSH")
    page.get_by_role("combobox", name="Protokol", exact=True).select_option("ssh")
    page.get_by_label("Kullanıcı adı", exact=True).fill("fixture")
    page.get_by_label("SSH parolası", exact=True).fill("fixture-login-secret")
    cli = page.get_by_label("Genişletilmiş CLI parolası", exact=False)
    expect(cli).to_have_attribute("type", "password")
    cli.fill("fixture-cli-secret")
    check("credential", "Genişletilmiş CLI parolası")
    page.get_by_role("combobox", name="Protokol", exact=True).select_option("snmpv2c")
    expect(cli).to_have_count(0)
    page.get_by_role("combobox", name="Protokol", exact=True).select_option("ssh")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("cell", name="HP 1950 SSH", exact=True)).to_be_visible()
    assert writes[-1]["secret"]["cli_password"] == "fixture-cli-secret" and "cli_password" not in {
        k: v for k, v in writes[-1].items() if k != "secret"
    }
    assert "fixture-cli-secret" not in page.locator("body").inner_text()
    page.goto("http://127.0.0.1:8237/#devices")
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Fixture 00")
    page.get_by_role("button", name="Kaydı düzenle", exact=True).click()
    adapter = page.get_by_role("combobox", name=re.compile("^Konfigürasyon adaptörü"))
    adapter.select_option("hp_1950")
    expect(adapter.get_by_role("option", name="HP 1950 · Comware 7", exact=True)).to_have_count(1)
    page.get_by_role("combobox", name="SSH / API profili", exact=True).select_option(label="HP 1950 SSH")
    check("device", "Konfigürasyon adaptörü")
    page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.get_by_role("button", name="Kaydı düzenle", exact=True).click()
    expect(adapter).to_have_value("hp_1950")
    page.keyboard.press("Escape")
    page.get_by_role("checkbox", name="Fixture 00 seç", exact=True).check()
    page.get_by_role("button", name="Toplu değiştir", exact=True).click()
    page.get_by_role("checkbox", name="Konfigürasyon adaptörü değiştir", exact=True).check()
    page.get_by_role("combobox", name="Konfigürasyon adaptörü değeri", exact=True).select_option("hp_1950")
    page.get_by_role("button", name="Seçilenlere uygula", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"hp1950": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
