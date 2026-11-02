"""Two-sided patch UI, deferred target creation and live updates without losing edits."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8215"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    sockets, errors = [], []
    page.route_web_socket("**/api/v1/ws", lambda ws: sockets.append(ws))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#cabinets")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Kuzey Kampüs", exact=False).click()
    page.get_by_role("button", name="Sunucu Odası", exact=True).click()
    page.get_by_role("button", name="K-01", exact=True).click()
    rack = page.get_by_role("dialog").last
    rack.get_by_label("Panel adı", exact=True).fill("FIBER-01")
    rack.get_by_label("Panel türü", exact=True).select_option("fiber")
    rack.get_by_label("Panel başlangıç U", exact=True).fill("41")
    rack.get_by_label("Port sayısı", exact=True).fill("2")
    rack.get_by_role("button", name="Patch panel ekle", exact=True).click()
    ports = page.get_by_role("dialog").last
    ports.get_by_role("button", name="Port 1 · Boş", exact=True).click()
    front = ports.get_by_role("group", name="İç bağlantı", exact=True)
    rear = ports.get_by_role("group", name="Dış bağlantı", exact=True)
    front.get_by_role("button", name="İç bağlantı ekle", exact=True).click()
    front.get_by_label("Bağlı cihaz", exact=True).select_option(label="Switch 1 · 198.51.100.1")
    expect(front.get_by_label("Bağlı cihaz portu", exact=True)).to_be_enabled()
    front.get_by_label("Bağlı cihaz portu", exact=True).select_option(label="A1")
    ports.get_by_label("Kablo modeli", exact=True).select_option("OM4")
    ports.get_by_label("Fiber türü", exact=True).select_option("multimode")
    rear.get_by_role("button", name="Dış bağlantı ekle", exact=True).click()
    rear.get_by_label("Karşı oda", exact=True).select_option(label="L-1/A/Elektrik Odası")
    rear.get_by_label("Karşı kabinet", exact=True).select_option(label="01")
    rear.get_by_label("Karşı patch panel", exact=True).select_option(label="FIBER-01 · 41U")
    rear.get_by_label("Karşı panel portu", exact=True).select_option(label="1")
    rear.get_by_label("Karşı uç · Bağlı cihaz", exact=True).select_option(label="Switch 2 · 198.51.100.2")
    expect(rear.get_by_label("Karşı uç · Bağlı cihaz portu", exact=True)).to_be_enabled()
    rear.get_by_label("Karşı uç · Bağlı cihaz portu", exact=True).select_option(label="B2")
    ports.get_by_role("button", name="Port bağlantısını kaydet", exact=True).click()
    expect(ports.get_by_role("status")).to_have_text("Port 1 kaydedildi.")
    expect(rear.get_by_text("Bağlı", exact=True)).to_be_visible()

    def check(name, focus):
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.wait_for_timeout(350)
                focus.scroll_into_view_if_needed()
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), (name, width)
                for dialog in page.get_by_role("dialog").all():
                    assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), (name, width)
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                issues = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                assert not issues, (name, width, theme, issues)
                page.screenshot(path=f"/tmp/netrix-patch-sides-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    check("linked", rear.get_by_label("Karşı panel portu", exact=True))
    cabinets = page.request.get(BASE + "/api/v1/cabinets?limit=100").json()["items"]
    source = next(c for c in cabinets if c["name"] == "K-01")
    panels = page.request.get(BASE + f"/api/v1/ipam/cabinets/{source['id']}/patch-panels").json()["items"]
    panel_id = panels[0]["id"]
    source_url = BASE + f"/api/v1/ipam/cabinets/{source['id']}/patch-panels/{panel_id}/ports"
    first = page.request.get(source_url).json()["items"][0]
    target = first["external"]
    remote_url = (
        BASE + f"/api/v1/ipam/cabinets/{target['cabinet_id']}/patch-panels/{target['panel_id']}/ports"
    )
    other = page.request.get(remote_url).json()["items"][0]
    assert other["device_name"] == "Switch 2" and other["port_name"] == "B2"
    assert other["external"]["device_name"] == "Switch 1" and other["external"]["port_name"] == "A1"
    ports.get_by_role("button", name="Port 2 · Boş", exact=True).click()
    rear.get_by_role("button", name="Dış bağlantı ekle", exact=True).click()
    rear.get_by_label("Karşı uç girişi", exact=True).select_option("planned")
    for label, value in [
        ("Karşı kat", "L-2"),
        ("Karşı bölüm", "B"),
        ("Karşı oda adı", "Gelecek Elektrik"),
        ("Karşı kabinet no", "02"),
        ("Karşı panel adı", "FIBER-02"),
        ("Karşı panel U (isteğe bağlı)", "41"),
        ("Karşı port numarası", "1"),
    ]:
        rear.get_by_label(label, exact=True).fill(value)
    rear.get_by_label("Karşı uç · Cihaz girişi", exact=True).select_option("manual")
    rear.get_by_label("Karşı uç · Bağlı cihaz adı / IP", exact=True).fill("Future Switch")
    rear.get_by_label("Karşı uç · Bağlı cihaz portu (manuel)", exact=True).fill("49")
    ports.get_by_role("button", name="Port bağlantısını kaydet", exact=True).click()
    expect(ports.get_by_role("status")).to_have_text("Port 2 kaydedildi.")
    expect(rear.get_by_text("Karşı uç bekleniyor", exact=True)).to_be_visible()
    check("pending", rear.get_by_label("Karşı oda adı", exact=True))
    sites = page.request.get(BASE + "/api/v1/sites?limit=100").json()["items"]
    campus = next(s for s in sites if not s["parent_id"])

    def post(path, data):
        response = page.request.post(BASE + "/api/v1" + path, data=data, headers={"X-Netrix-Request": "1"})
        assert response.status == 201, response.text()
        return response.json()

    room = post(
        "/sites",
        dict(
            name="Gelecek Elektrik",
            parent_id=campus["id"],
            institution_id=campus["institution_id"],
            floor_number="L-2",
            department_name="B",
        ),
    )
    cab = post("/cabinets", dict(name="02", site_id=campus["id"], sub_site_id=room["id"], units=42))
    post(
        f"/ipam/cabinets/{cab['id']}/patch-panels",
        dict(name="FIBER-02", kind="fiber", start_unit=41, port_count=2),
    )
    assert sockets
    sockets[0].send('{"type":"refresh"}')
    expect(rear.get_by_text("Bağlı", exact=True)).to_be_visible(timeout=15000)
    expect(rear.get_by_label("Karşı oda", exact=True).locator("option:checked")).to_have_text(
        "L-2/B/Gelecek Elektrik"
    )
    expect(rear.get_by_label("Karşı uç · Bağlı cihaz adı / IP", exact=True)).to_have_value("Future Switch")
    ports.get_by_label("Port numarası", exact=True).fill("Unsaved label")
    sockets[0].send('{"type":"refresh"}')
    page.wait_for_timeout(2000)
    expect(ports.get_by_label("Port numarası", exact=True)).to_have_value("Unsaved label")
    # Device reverse records use the same rear relation, without duplicating inventory.
    ports.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("dialog").last.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.evaluate("location.hash='devices'")
    page.get_by_role("button", name="Switch 2", exact=True).click()
    detail = page.get_by_role("dialog").last
    linked_row = detail.get_by_role("row").filter(has=page.get_by_role("cell", name="FIBER-01", exact=False))
    expect(linked_row).to_contain_text("Switch 1 / A1")
    assert not errors, errors
    browser.close()
print(
    "PASS: front/rear editors, reciprocal device/port info, deferred creation, live matching, unsaved edit preservation, desktop/mobile, themes and accessibility"
)
