"""Real API address matrix: colors, navigation, creation, responsive layout and WCAG."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8247"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, writes, reads = [], [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: (writes if r.method != "GET" else reads).append(r.url))
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    inspect_button = page.get_by_role("button", name="VLAN incele", exact=True)
    # The general VLAN list must never expose this context-only action.
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        expect(inspect_button).to_have_count(0)
        page.screenshot(path=f"/tmp/netrix-inspector-scope-list-{width}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(inspect_button).to_be_visible()
    a, b = (
        inspect_button.bounding_box(),
        page.get_by_role("button", name="Yeni IP kaydı", exact=True).bounding_box(),
    )
    assert abs(a["y"] - b["y"]) < 1 and abs(a["height"] - b["height"]) < 1
    read_start = len(reads)
    inspect_button.click()
    dialog = page.get_by_role("dialog", name="VLAN incele", exact=True)
    expect(dialog.get_by_role("combobox")).to_have_count(0)
    context = dialog.locator(".vlan-inspector-context strong")
    expect(context).to_have_text("VLAN-20 / SERVER | 192.0.2.0/24")
    tiles = dialog.locator(".vlan-address-tile")
    expect(tiles).to_have_count(254)
    assert not any("/api/v1/vlans" in u for u in reads[read_start:]), reads[read_start:]
    expect(dialog.get_by_role("button", name="192.0.2.11 · Dolu · IP ayrıntıları", exact=True)).to_have_class(
        "vlan-address-tile inspector-occupied"
    )
    expect(dialog.get_by_role("button", name="192.0.2.13 · Boş · IP ekle", exact=True)).to_have_class(
        "vlan-address-tile inspector-free"
    )
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            vlan_box = context.bounding_box()
            search_box = dialog.get_by_role("textbox", name="IP adresine git", exact=True).bounding_box()
            if width > 600:
                assert abs(vlan_box["y"] - search_box["y"]) < 1, (vlan_box, search_box)
                assert abs(vlan_box["height"] - search_box["height"]) < 1
            boxes = tiles.evaluate_all(
                "es=>es.slice(0,3).map(e=>{const r=e.getBoundingClientRect();return {y:r.y,w:r.width,h:r.height}})"
            )
            assert all(
                abs(b["y"] - boxes[0]["y"]) < 1
                and abs(b["h"] - boxes[0]["h"]) < 1
                and abs(b["w"] - boxes[0]["w"]) < 1
                for b in boxes
            )
            free = dialog.locator(".vlan-address-tile.inspector-free").first
            occupied = dialog.locator(".vlan-address-tile.inspector-occupied").first
            assert free.evaluate("e=>getComputedStyle(e).backgroundColor") != occupied.evaluate(
                "e=>getComputedStyle(e).backgroundColor"
            )
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            assert not violations, violations
            page.screenshot(path=f"/tmp/netrix-inspector-scope-{width}-{theme}.png")
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        search = dialog.get_by_role("textbox", name="IP adresine git", exact=True)
        search.fill("192.0.2.11")
        search.press("Enter")
        tile = dialog.get_by_role("button", name="192.0.2.11 · Dolu · IP ayrıntıları", exact=True)
        expect(tile).to_have_attribute("data-search-target", "true")
        expect(tile).to_be_focused()
        expect(dialog.get_by_text("192.0.2.11 bulundu", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 1000})
    dialog.get_by_role("button", name="192.0.2.11 · Dolu · IP ayrıntıları", exact=True).click()
    detail = page.get_by_role("dialog")
    expect(detail.get_by_role("heading", level=2)).to_have_text("192.0.2.11 · IP ayrıntıları")
    expect(detail.get_by_text("MANUAL-FW-11", exact=False).first).to_be_visible()
    detail.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="VLAN alanlarına dön", exact=True).click()
    expect(inspect_button).to_have_count(0)
    page.get_by_role("button", name="198.18.0.0/23", exact=True).click()
    inspect_button.click()
    expect(context).to_have_text("VLAN-30 / BACKUP | 198.18.0.0/23")
    expect(tiles).to_have_count(256)
    dialog.get_by_role("button", name="Sonraki", exact=True).click()
    expect(tiles).to_have_count(254)
    expect(dialog.get_by_role("button", name="198.18.1.254 · Boş · IP ekle", exact=True)).to_be_visible()
    dialog.get_by_role("textbox", name="IP adresine git", exact=True).fill("198.18.0.20")
    dialog.get_by_role("button", name="IP adresine git", exact=True).click()
    expect(tiles).to_have_count(256)
    dialog.get_by_role("button", name="198.18.0.20 · Boş · IP ekle", exact=True).click()
    form = page.get_by_role("dialog")
    expect(form.get_by_role("heading")).to_have_text("Yeni kayıt · IP adresleri")
    expect(form.get_by_role("combobox", name="IP adresi", exact=True)).to_have_value("198.18.0.20")
    expect(form.get_by_role("combobox", name="VLAN", exact=True).locator("option:checked")).to_have_text(
        "BACKUP"
    )
    form.get_by_label("Hostname", exact=True).fill("GRID-CREATED")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/addresses")) as saved:
        form.get_by_role("button", name="Kaydı kaydet", exact=True).click()
    assert saved.value.status == 201, saved.value.text()
    expect(page.get_by_role("cell", name="GRID-CREATED", exact=True)).to_be_visible()
    inspect_button.click()
    expect(context).to_have_text("VLAN-30 / BACKUP | 198.18.0.0/23")
    expect(
        dialog.get_by_role("button", name="198.18.0.20 · Dolu · IP ayrıntıları", exact=True)
    ).to_be_visible()
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="VLAN alanlarına dön", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    inspect_button.click()
    expect(context).to_have_text("VLAN-20 / SERVER | 192.0.2.0/24")
    expect(dialog.get_by_role("combobox")).to_have_count(0)
    assert not errors, errors
    assert len(writes) == 2 and not any(
        "/scan" in u or "/discover" in u or u.endswith("/inspection") for u in writes
    ), writes
    browser.close()
    print(
        "PASS: VLAN-only action without general selector/list request, matrix colors, occupied details, vacant creation, pagination/search, responsive themes/WCAG, no scans"
    )
