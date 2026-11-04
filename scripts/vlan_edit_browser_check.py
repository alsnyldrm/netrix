"""One VLAN editor persists metadata and ping settings without network jobs."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8247"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, writes = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: writes.append((r.method, r.url)) if r.method != "GET" else None)
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True)).to_have_count(0)
    page.get_by_role("button", name="192.0.2.0/24 düzenle", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading")).to_have_text("Kaydı düzenle · VLAN alanları")
    for label in ("VLAN adı", "VLAN ID (1–4094)", "Domain", "IP bloğu / CIDR", "VRF", "DNS sunucusu",
                  "IP kullanım uyarı eşiği (%)", "Ping aralığı (saniye)", "IP durumunu düzenli kontrol et",
                  "Kurum", "Lokasyon", "Açıklama"):
        expect(dialog.get_by_label(label, exact=True)).to_have_count(1)
    expect(dialog.get_by_label("Yeni sunucuları düzenli ekle", exact=True)).to_have_count(0)
    expect(dialog.get_by_text("VLAN kaydedildiğinde IP taraması otomatik başlar.", exact=True)).to_have_count(0)
    dns = dialog.get_by_role("combobox", name="DNS sunucusu", exact=True)
    previous_dns = dns.input_value()
    threshold = dialog.get_by_label("IP kullanım uyarı eşiği (%)", exact=True)
    interval = dialog.get_by_label("Ping aralığı (saniye)", exact=True)
    ping = dialog.get_by_role("checkbox", name="IP durumunu düzenli kontrol et", exact=True)
    assert threshold.get_attribute("min") == "1" and threshold.get_attribute("max") == "100"
    assert interval.get_attribute("min") == "10" and interval.get_attribute("max") == "86400"
    interval.fill("9")
    assert not interval.evaluate("e=>e.checkValidity()")
    interval.fill("45")
    threshold.fill("65")
    dns.select_option("")
    ping.uncheck()
    dialog.get_by_label("VLAN adı", exact=True).fill("SERVER-EDITED")
    dialog.get_by_label("Açıklama", exact=True).fill("Tek formdan düzenlendi")
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            dialog.get_by_label("VLAN adı", exact=True).scroll_into_view_if_needed()
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            boxes = dialog.locator(".form-field > input,.form-field > select,.form-field > .checkbox-control").evaluate_all(
                "es=>es.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})")
            assert len(boxes) == 12 and all(abs(b["h"] - 40) < 1 for b in boxes), boxes
            if width > 480:
                for index in range(0, len(boxes), 2):
                    assert abs(boxes[index]["y"] - boxes[index+1]["y"]) < 1, boxes
                    assert abs(boxes[index]["w"] - boxes[index+1]["w"]) < 1, boxes
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id)")
            page.screenshot(path=f"/tmp/netrix-vlan-editor-{width}-{theme}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    with page.expect_response(lambda r: r.request.method == "PUT" and "/api/v1/vlans/" in r.url) as response:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert response.value.ok, response.value.text()
    saved = response.value.json()
    assert saved["name"] == "SERVER-EDITED" and saved["description"] == "Tek formdan düzenlendi"
    assert saved["dns_server_id"] is None and saved["warning_threshold"] == 65
    assert saved["ping_interval"] == 45 and not saved["ping_enabled"]
    expect(dialog).to_have_count(0)
    page.get_by_role("button", name="192.0.2.0/24 düzenle", exact=True).click()
    expect(threshold).to_have_value("65")
    expect(interval).to_have_value("45")
    expect(ping).not_to_be_checked()
    dns.select_option(previous_dns)
    ping.check()
    with page.expect_response(lambda r: r.request.method == "PUT" and "/api/v1/vlans/" in r.url) as restored:
        dialog.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert restored.value.json()["ping_enabled"] and restored.value.json()["dns_server_id"] == previous_dns
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    expect(interval).to_have_value("30")
    expect(ping).to_be_checked()
    dialog.get_by_role("button", name="Vazgeç", exact=True).click()
    assert len(writes) == 3 and [method for method, _ in writes] == ["POST", "PUT", "PUT"], writes
    assert not any("/settings" in url or "/scan" in url or "/discover" in url for _, url in writes), writes
    assert not errors, errors
    browser.close()
    print("PASS: single VLAN editor, unique fields, defaults, metadata/ping/DNS persistence, desktop/mobile alignment and WCAG; no scans")
