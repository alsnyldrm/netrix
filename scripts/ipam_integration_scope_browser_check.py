"""DHCP/VMware-only forms and authorization-free VLAN settings on a local fixture."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8248")
assert BASE.startswith("http://127.0.0.1:")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))

    def check(name):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                dialog = page.get_by_role("dialog")
                if dialog.count():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                    assert "yetkilendirilmiştir" not in dialog.inner_text()
                    fields = dialog.locator(".ipam-field").evaluate_all(
                        'els=>els.map(e=>{const r=e.getBoundingClientRect();const c=e.querySelector("input,select,textarea");return {x:r.x,cx:c?.getBoundingClientRect().x};})'
                    )
                    assert all(abs(f["x"] - f["cx"]) <= 1 for f in fields if f["cx"] is not None), fields
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"/tmp/netrix-scope-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(BASE + "/#integrations")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    check("integrations")
    page.get_by_role("button", name="Entegrasyon ekle", exact=True).click()
    kind = page.get_by_role("combobox", name="Entegrasyon türü", exact=True)
    assert kind.locator("option").evaluate_all("els=>els.map(e=>e.value)") == ["vcenter", "windows_dhcp"]
    for value, port in [("windows_dhcp", "5986"), ("vcenter", "443")]:
        kind.select_option(value)
        expect(page.get_by_label("Bağlantı portu", exact=True)).to_have_value(port)
        expect(page.get_by_label("SNMP erişim profili", exact=True)).to_have_count(0)
    check("integration-form")
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.goto(BASE + "/#vlans")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
    check("vlan-settings")
    ping = page.get_by_role("checkbox", name="IP durumunu düzenli kontrol et", exact=True)
    discover = page.get_by_role("checkbox", name="Yeni sunucuları düzenli ekle", exact=True)
    expect(ping).to_be_enabled()
    expect(discover).to_be_enabled()
    ping.check()
    discover.check()
    page.get_by_role("button", name="Ayarları kaydet", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
    expect(ping).to_be_checked()
    expect(discover).to_be_checked()
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    check("vlan-form")
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {
                "only_dhcp_vmware": "PASS",
                "no_scan_approval": "PASS",
                "schedule_persistence": "PASS",
                "axe": reports,
            }
        )
    )
    browser.close()
