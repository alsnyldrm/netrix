"""Check block summary, explicit scan actions and active-only toggle using local fixtures."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    header = page.locator(".ipam-block-header")
    expect(header).to_be_visible()
    for text in ("Ağ bloğunu düzenle", "Ağ bloğu ayarları", "Yeni sunucuları ekle", "IP durumunu kontrol et"):
        expect(header.get_by_role("button", name=text, exact=True)).to_have_count(0)
    assert "Doluluk, son ping" not in header.inner_text()
    assert "Uyarı eşiği" not in header.inner_text()
    expect(header.get_by_label("Ağ bloğu kullanımı")).to_contain_text("aktif IP")
    toggle = page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True)
    expect(page.get_by_role("checkbox", name="Yalnızca aktif IP’ler", exact=True)).to_have_count(0)
    expect(toggle).to_have_attribute("aria-pressed", "false")
    # Exercise real filtered reads, including keyboard interaction and reverting.
    with page.expect_response(lambda r: "/addresses?active_only=true" in r.url):
        toggle.focus()
        toggle.press("Space")
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Ağ içindeki aktif IP adresleri", exact=True)).to_be_visible()
    with page.expect_response(lambda r: "/addresses?active_only=false" in r.url):
        toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "false")
    Path("artifacts").mkdir(exist_ok=True)
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            for active in (False, True):
                if toggle.get_attribute("aria-pressed") != str(active).lower():
                    toggle.click()
                expect(toggle).to_have_attribute("aria-pressed", str(active).lower())
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                assert header.evaluate("e=>e.scrollWidth<=e.clientWidth")
                if active:
                    assert toggle.evaluate("e=>getComputedStyle(e).color===getComputedStyle(document.documentElement).getPropertyValue('--success').trim() || getComputedStyle(e).borderTopColor===getComputedStyle(e).color")
                if width in (1440, 375):
                    columns = page.get_by_role("button", name="Sütunlar", exact=True).bounding_box()
                    button = toggle.bounding_box()
                    assert abs(columns["y"] + columns["height"] / 2 - button["y"] - button["height"] / 2) < 1
                    assert button["height"] == 30
                    assert button["width"] < 100
                if width == 1440:
                    summary = header.locator(".ipam-block-usage").bounding_box()
                    title = header.locator(".ipam-block-title").bounding_box()
                    assert summary["x"] > title["x"] + title["width"]
                    assert abs(summary["y"] - title["y"]) < 1
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                issues = page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)")
                assert not issues, (width, theme, active, issues)
                header.scroll_into_view_if_needed()
                page.screenshot(path=f"artifacts/ipam-panel-{width}-{theme}-{active}.png")
    # Intercept scan submissions: verify dispatch without starting real scans.
    calls = []

    def submitted(route):
        calls.append(route.request.url.rsplit("/", 1)[-1])
        assert route.request.method == "POST"
        route.fulfill(status=202, json={"id": "fixture-scan", "status": "succeeded", "progress": 0, "total": 0})

    page.route("**/api/v1/ipam/prefixes/*/ping", submitted)
    page.route("**/api/v1/ipam/prefixes/*/discover", submitted)
    page.set_viewport_size({"width": 1440, "height": 1000})
    header.get_by_role("button", name="Kayıtlı IP’lere ping at", exact=True).click()
    expect(page.locator(".ipam-job")).to_contain_text("İşlem tamamlandı.")
    header.get_by_role("button", name="Ağdaki IP’leri keşfet", exact=True).click()
    expect(page.locator(".ipam-job")).to_contain_text("İşlem tamamlandı.")
    assert calls == ["ping", "discover"], calls
    # Settings remain available on the network list, outside the simplified header.
    header.get_by_role("button", name="Ağ blokları", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    assert not errors, errors
    browser.close()
    print("PASS: summary, removed controls, toggle/filter, scan dispatch, settings access, 12 layout/theme/state and axe checks")
