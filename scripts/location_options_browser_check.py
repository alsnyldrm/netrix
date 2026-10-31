"""Validate primary/child choices across forms using discovery_profiles_fixture only."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8232/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def check_layout(name):
        dialog = page.get_by_role("dialog")
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            site = dialog.get_by_role("combobox", name="Lokasyon", exact=True)
            if not site.count():
                site = dialog.get_by_role("combobox", name="Lokasyon değeri", exact=True)
            site.scroll_into_view_if_needed()
            expect(site).to_be_in_viewport()
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            # Controls on a shared row retain equal height and a common top edge.
            boxes = dialog.locator(
                ".form-grid > .form-field > input, .form-grid > .form-field > select"
            ).evaluate_all(
                "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
            )
            if boxes:
                assert max(b["h"] for b in boxes) - min(b["h"] for b in boxes) < 1
                if width == 375:
                    assert max(b["x"] for b in boxes) - min(b["x"] for b in boxes) < 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            assert not violations, (name, width, violations)
            page.screenshot(path=f"artifacts/location-options-{name}-{width}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    for name in ("devices", "prefixes", "addresses", "cabinets"):
        page.goto("http://127.0.0.1:8232/#" + name)
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="Yeni kayıt", exact=True).click()
        dialog = page.get_by_role("dialog")
        institution = dialog.get_by_role("combobox", name="Kurum", exact=True)
        if institution.count():
            institution.select_option(label="Kuzey Üniversitesi")
        site = dialog.get_by_role("combobox", name="Lokasyon", exact=True)
        labels = site.locator("option").all_text_contents()
        assert "Kuzey Kampüs" in labels
        assert not any("Sunucu Odası" in text for text in labels), (name, labels)
        site.select_option(label="Kuzey Kampüs")
        sub = dialog.get_by_role("combobox", name="Alt lokasyon", exact=True)
        if sub.count():
            labels = sub.locator("option").all_text_contents()
            assert "Kuzey Kampüs Sunucu Odası" in labels
            assert "Güney Kampüs Sunucu Odası" not in labels
            sub.select_option(label="Kuzey Kampüs Sunucu Odası")
        check_layout(name)
        dialog.get_by_role("button", name="Vazgeç", exact=True).click()

    page.goto("http://127.0.0.1:8232/#devices")
    page.wait_for_load_state("networkidle")
    page.locator("tbody input[type=checkbox]").first.check()
    page.get_by_role("button", name="Toplu değiştir", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("checkbox", name="Lokasyon değiştir", exact=True).check()
    site = dialog.get_by_role("combobox", name="Lokasyon değeri", exact=True)
    expect(site.locator("option")).to_have_count(3)
    assert not any("Sunucu Odası" in text for text in site.locator("option").all_text_contents())
    site.select_option(label="Kuzey Kampüs")
    check_layout("device-bulk")
    assert not errors, errors
    browser.close()
print(
    "PASS: primary locations only in inventory, bulk editor, prefixes, IPs and cabinets; child fields preserved; desktop/mobile alignment and accessibility"
)
