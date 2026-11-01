"""Menus/settings search, cross-screen records, and actual refresh with preserved state."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8215"
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page = context.new_page()
    page.set_default_timeout(10000)
    errors, forced = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "request", lambda r: forced.append(r.url) if r.headers.get("cache-control") == "no-cache" else None
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#settings")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_role("heading", name="Platform durumu", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    menu_count = page.locator(".nav-item").count()

    def palette(query=""):
        page.get_by_role("button", name="Komut paletini aç (Ctrl K)").click()
        dialog = page.get_by_role("dialog", name="Çalışma alanında gezin")
        expect(dialog).to_be_visible()
        search = dialog.get_by_role("textbox", name="Menü, ayar, cihaz veya VLAN ara")
        try:
            search.fill(query)
        except Exception:
            print(
                {
                    "errors": errors,
                    "dialog_text": dialog.inner_text()[:500],
                    "input": dialog.locator("input").evaluate_all("els=>els.map(e=>e.outerHTML)"),
                }
            )
            page.screenshot(path="/tmp/netrix-palette-failure.png")
            raise
        return dialog, search

    dialog, search = palette()
    assert dialog.get_by_role("region", name="Tüm menüler").get_by_role("button").count() == menu_count
    search.fill("snmp")
    expect(dialog.get_by_role("button", name="Erişim kasası Yönetim", exact=True)).to_be_visible()
    search.fill("parolamı")
    search.press("ArrowDown")
    expect(
        dialog.get_by_role(
            "button", name="Parolamı değiştir Sistem odası · Hesap ve şifre ayarları", exact=True
        )
    ).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#settings-password")).to_be_focused()

    dialog, search = palette("Switch 1")
    device = dialog.get_by_role("region", name="Cihaz sonuçları").get_by_role("button").first
    expect(device).to_contain_text("Switch 1")
    device.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()

    dialog, search = palette("192.0.2.0")
    vlan = dialog.get_by_role("region", name="VLAN sonuçları").get_by_role("button").first
    expect(vlan).to_contain_text("SERVER")
    vlan.click()
    expect(page.locator(".ipam-block-header")).to_contain_text("SERVER")
    expect(page.get_by_role("button", name="192.0.2.10", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    address_search = page.get_by_placeholder("Tüm alanlarda ara…")
    address_search.fill("192.0.2.10")
    expect(page.get_by_text("app-01.example.test", exact=True)).to_be_visible()
    # Warm cache, then change the DB without invalidating it. Refresh must bypass it.
    changed = page.evaluate(
        "async()=>{const r=await fetch('/fixture/change-hostname',{method:'POST',headers:{'X-Netrix-Request':'1'}});return r.ok}"
    )
    assert changed
    page.get_by_role("button", name="Verileri yenile", exact=True).click()
    expect(page.get_by_role("button", name="Verileri yenile", exact=True)).to_be_enabled(timeout=15000)
    expect(page.get_by_text("refreshed.example.test", exact=True)).to_be_visible()
    expect(address_search).to_have_value("192.0.2.10")
    expect(page.locator(".ipam-block-header")).to_contain_text("SERVER")
    assert any("/ipam/vlans/" in url and "/addresses?" in url for url in forced)

    # The settings screen previously loaded once and ignored every refresh.
    dialog, search = palette("Platform durumu")
    search.press("Enter")
    expect(page.locator("#settings-platform")).to_be_focused()
    page.wait_for_load_state("networkidle")
    system_reads = []

    def system(route):
        result = route.fetch().json()
        system_reads.append(1)
        result["version"] = "refresh-" + str(len(system_reads))
        route.fulfill(json=result)

    page.route("**/api/v1/system", system)
    page.get_by_role("button", name="Verileri yenile", exact=True).click()
    expect(page.get_by_role("button", name="Verileri yenile", exact=True)).to_be_enabled()
    assert system_reads
    expect(page.get_by_text("vrefresh-" + str(len(system_reads)), exact=True)).to_be_visible()
    prior_reads = len(system_reads)
    page.get_by_role("button", name="Verileri yenile", exact=True).click()
    expect(page.get_by_role("button", name="Verileri yenile", exact=True)).to_be_enabled()
    assert len(system_reads) > prior_reads
    expect(page.get_by_text("vrefresh-" + str(len(system_reads)), exact=True)).to_be_visible()
    page.unroute("**/api/v1/system", system)

    def fail(route):
        route.fulfill(status=503, json={"detail": "Fixture temporary failure"})

    page.route("**/api/v1/system", fail)
    page.get_by_role("button", name="Verileri yenile", exact=True).click()
    expect(page.get_by_role("button", name="Verileri yenile", exact=True)).to_be_enabled()
    expect(page.get_by_text("Yenileme tamamlanamadı: Fixture temporary failure", exact=True)).to_be_visible()
    page.unroute("**/api/v1/system", fail)
    page.get_by_role("button", name="Verileri yenile", exact=True).click()
    expect(page.get_by_role("button", name="Verileri yenile", exact=True)).to_be_enabled()

    dialog, search = palette("qzx-no-result-987")
    expect(dialog.get_by_role("status")).to_have_text("Eşleşen menü, ayar, cihaz veya VLAN bulunamadı.")
    reports = {}
    for width, height in ((1440, 1000), (375, 812), (320, 812)):
        for theme in ("light", "dark"):
            search.fill("")
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            rows = dialog.locator(".command-results button")
            assert all(row.bounding_box()["height"] >= 40 for row in rows.all())
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            page.screenshot(path=f"/tmp/netrix-workspace-search-{width}-{theme}.png")
    search.fill("")
    search.press("ArrowDown")
    page.keyboard.press("End")
    expect(dialog.get_by_role("button", name="Sistem odası Yönetim", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    page.keyboard.press("Control+k")
    expect(page.get_by_role("dialog", name="Çalışma alanında gezin")).to_be_visible()
    assert not errors and not any(reports.values()), (errors, reports)
    print(
        json.dumps(
            {
                "menus": menu_count,
                "settings_shortcuts": "PASS",
                "remote_record_search": "PASS",
                "vlan_refresh": "PASS",
                "settings_refresh": "PASS",
                "refresh_error_recovery": "PASS",
                "keyboard": "PASS",
                "views": len(reports),
                "axe": reports,
                "errors": errors,
            }
        )
    )
    browser.close()
