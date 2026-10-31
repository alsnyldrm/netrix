"""Search both endpoints and all port observations in the topology detail selector."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8231")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/#neighbors")
    page.get_by_label("E-posta").fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    detail = page.locator(".topology-link-detail")
    search = detail.get_by_role("searchbox", name="Bağlantılarda ara", exact=True)
    select = detail.get_by_role("combobox", name="Bağlantı ayrıntısı", exact=True)
    expect(select.locator("option")).to_have_count(5)
    for query in [
        "controller",
        "CONTROLLER",
        "198.51.100.3",
        "b1",
        "GE0/0/4",
        "trk7",
        "controller b1",
        "Gİ1/0/9",
        "d7",
    ]:
        search.fill(query)
        expect(select.locator("option")).to_have_count(2)
        expect(detail.get_by_role("status")).to_have_text("1 bağlantı bulundu.")
        select.select_option(index=1)
        expect(detail.locator(".topology-port-heading")).to_be_visible()
    expect(detail.locator("ul")).to_contain_text("Gi1/0/9")
    expect(detail.locator("ul")).to_contain_text("D7")
    search.fill("no-such-connection")
    expect(select).to_be_disabled()
    expect(detail.get_by_role("status")).to_have_text("0 bağlantı bulundu.")
    expect(detail.locator(".topology-port-heading")).to_have_count(0)
    search.fill("   ")
    expect(select).to_be_enabled()
    expect(select.locator("option")).to_have_count(5)
    search.fill("B1")
    search.focus()
    search.press("Tab")
    expect(select).to_be_focused()
    select.select_option(index=1)
    expect(detail.locator("ul")).to_contain_text("GE0/0/4")
    expect(detail.locator("ul")).to_contain_text("Trk7")
    expect(page.locator(".topology-map")).to_have_count(0)
    for width, height in [(1440, 1000), (375, 812), (812, 375)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ["light", "dark"]:
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            boxes = detail.locator(".topology-link-filters input,.topology-link-filters select").evaluate_all(
                "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,h:r.height};})"
            )
            assert all(b["h"] >= 44 for b in boxes)
            if width > 600:
                assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1
            else:
                assert abs(boxes[0]["x"] - boxes[1]["x"]) < 1 and boxes[1]["y"] > boxes[0]["y"]
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            issues = page.evaluate(
                "async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            assert not issues, (width, theme, issues)
            detail.screenshot(path=f"artifacts/connection-search-{width}-{theme}.png")
    assert not errors, errors
    print(
        "PASS: endpoint names/IPs, local/remote/reverse ports, trunk, case folding, multiple terms, empty result, clear, keyboard, desktop/mobile alignment and axe"
    )
    browser.close()
