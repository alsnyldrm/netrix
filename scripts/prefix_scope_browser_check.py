"""Verify visible prefix scope, persistence and unlinking on the isolated IPAM fixture."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def open_settings():
        page.get_by_role("button", name="192.0.2.0/24 ayarları", exact=True).click()
        return page.get_by_role("combobox", name="Keşif kapsamı", exact=True)

    def save_settings():
        with page.expect_response(
            lambda response: "/settings" in response.url and response.request.method == "PUT"
        ) as pending:
            page.get_by_role("button", name="Ayarları kaydet", exact=True).click()
        assert pending.value.ok, pending.value.text()
        expect(page.get_by_role("dialog")).to_have_count(0)
        return pending.value.json()

    scope = open_settings()
    selected_id = scope.input_value()
    assert selected_id
    expect(scope.locator("option:checked")).to_have_text("Yetkili kampüs ağı · 192.0.2.0/24")
    Path("artifacts").mkdir(exist_ok=True)
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            dialog = page.get_by_role("dialog")
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            fields = dialog.locator(".ipam-field input, .ipam-field select")
            boxes = fields.evaluate_all(
                "els=>els.map(e=>{let b=e.getBoundingClientRect();return {x:b.x,w:b.width,h:b.height}})"
            )
            assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) < 1
            assert abs(boxes[0]["x"] - boxes[1]["x"]) < 1
            if width == 375:
                assert max(b["x"] for b in boxes) - min(b["x"] for b in boxes) < 1
                assert max(b["w"] for b in boxes) - min(b["w"] for b in boxes) < 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            assert not violations, (width, theme, violations)
            page.screenshot(path=f"artifacts/prefix-scope-{width}-{theme}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    # Saving unrelated settings must retain the visible, existing relationship.
    page.get_by_label("IP kullanım uyarı eşiği (%)", exact=True).fill("65")
    saved = save_settings()
    assert saved["scope_id"] == selected_id
    scope = open_settings()
    expect(scope).to_have_value(selected_id)
    # Explicit unlink is persistent and leaves scan authorization/settings untouched.
    scope.select_option("")
    unlinked = save_settings()
    assert unlinked["scope_id"] is None
    assert unlinked["warning_threshold"] == 65
    assert unlinked["scan_authorized"] == saved["scan_authorized"]
    assert unlinked["ping_enabled"] == saved["ping_enabled"]
    assert unlinked["discovery_enabled"] == saved["discovery_enabled"]
    scope = open_settings()
    expect(scope).to_have_value("")
    # The scope itself remains available and can be linked again.
    scope.select_option(selected_id)
    assert save_settings()["scope_id"] == selected_id
    scope = open_settings()
    scope.select_option("")
    save_settings()
    # With the prefix association removed, the FK no longer blocks scope deletion.
    response = page.context.request.delete(
        f"http://127.0.0.1:8211/api/v1/scopes/{selected_id}",
        headers={"X-Netrix-Request": "1"},
    )
    assert response.ok, response.text()
    assert not errors, errors
    browser.close()
    print("PASS: scope visibility, save, unlink, relink, deletion, 6 responsive/theme/accessibility checks")
