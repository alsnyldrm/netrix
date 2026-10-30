"""Topology UI regression checks, against a disposable local fixture only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8216")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    # Headless Chromium hides scrollbars by default; retain desktop scrollbar
    # geometry so overflow/ResizeObserver regressions are actually exercised.
    browser = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base)
    page.get_by_label("E-posta").fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir").click()
    page.wait_for_load_state("networkidle")
    page.goto(base + "/#topology")
    page.wait_for_load_state("networkidle")
    expect(page.locator(".topology-device").first).to_be_visible()
    page.get_by_role("region", name="Bağlantı cihazları").get_by_role(
        "button", name="HP-SW-BB-01-A-00-01", exact=True
    ).click()
    expect(page.get_by_text("18:7a:3b:4f:14:40", exact=True)).to_be_visible()
    expect(page.get_by_text("Kullanıcı doğrulaması", exact=True)).to_be_visible()

    def node(name):
        return page.get_by_role("button", name=name + " cihazını görüntüle")

    boxes = {
        name: node(name).bounding_box()
        for name in ["FG-FW-GW-A-01-00-01", "HP-SW-BB-01-A-00-01", "Controller", "Edge-01", "Edge-02"]
    }
    assert (
        boxes["FG-FW-GW-A-01-00-01"]["y"]
        < boxes["HP-SW-BB-01-A-00-01"]["y"]
        < boxes["Edge-01"]["y"]
        < boxes["Edge-02"]["y"]
    )
    assert abs(boxes["Controller"]["y"] - boxes["HP-SW-BB-01-A-00-01"]["y"]) < 1
    assert page.locator(".topology-edge").count() == 4
    before = node("Edge-01").bounding_box()["width"]
    page.get_by_role("button", name="Haritayı küçült").click()
    expect(page.get_by_label("Harita yakınlaştırma oranı")).to_have_text("80%")
    page.wait_for_function(
        """(width) => document.querySelector('[aria-label="Edge-01 cihazını görüntüle"]').getBoundingClientRect().width < width - 1""",
        arg=before,
    )
    page.get_by_role("button", name="Haritayı büyüt").click()
    expect(page.get_by_label("Harita yakınlaştırma oranı")).to_have_text("100%")
    page.wait_for_function(
        """(width) => Math.abs(document.querySelector('[aria-label="Edge-01 cihazını görüntüle"]').getBoundingClientRect().width - width) < 1""",
        arg=before,
    )
    page.get_by_role("button", name="Sığdır", exact=True).click()
    # Fractional CSS pixels (as with browser zoom) used to toggle scrollbars
    # every frame while the sidebar was open. Allow its transition to finish,
    # then require the viewport, canvas and node transform to stay unchanged.
    page.emulate_media(reduced_motion="no-preference")
    for browser_zoom in [1, 1.25, 1.5]:
        page.evaluate("zoom => document.documentElement.style.zoom = zoom", str(browser_zoom))
        for width in [1384, 1389, 1440]:
            page.set_viewport_size({"width": width, "height": 1000})
            for collapsed in [False, True]:
                toggle = "Menüyü daralt" if collapsed else "Menüyü genişlet"
                if page.get_by_role("button", name=toggle, exact=True).count():
                    page.get_by_role("button", name=toggle, exact=True).click()
                page.wait_for_timeout(350)
                samples = page.evaluate("""() => new Promise(resolve => {
                    const states = new Set();
                    let frames = 0;
                    function sample() {
                        const viewport = document.querySelector('.topology-viewport');
                        const canvas = document.querySelector('.topology-canvas');
                        const nodes = document.querySelector('.topology-nodes');
                        states.add(JSON.stringify([
                            viewport.clientWidth, viewport.clientHeight,
                            canvas.getBoundingClientRect().width,
                            canvas.getBoundingClientRect().height,
                            nodes.style.transform, nodes.style.left
                        ]));
                        if (++frames < 30) requestAnimationFrame(sample);
                        else resolve([...states]);
                    }
                    requestAnimationFrame(sample);
                })""")
                assert len(samples) == 1, (browser_zoom, width, collapsed, samples)
    page.evaluate("() => document.documentElement.style.removeProperty('zoom')")
    page.emulate_media(reduced_motion="reduce")
    page.get_by_role("button", name="Menüyü genişlet", exact=True).click()
    for width, height in [(1440, 1000), (375, 812), (812, 375)]:
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(200)
        for theme in ["dark", "light"]:
            page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)
            page.screenshot(path=f"artifacts/topology-{width}-{theme}.png", full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            for button in page.locator(".topology-controls button").all():
                assert button.bounding_box()["height"] >= 44
            assert page.locator(".topology-device").evaluate_all(
                "nodes => nodes.every(n => n.children.length === 2 && [...n.children].every(c => c.scrollWidth <= c.clientWidth + 1))"
            )
    page.set_viewport_size({"width": 375, "height": 812})
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(node("Edge-01")).to_be_attached()
    assert node("Edge-01").bounding_box()["width"] >= 200
    page.screenshot(path="artifacts/topology-mobile-readable-default.png", full_page=True)
    page.get_by_role("button", name="Sığdır", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('.topology-viewport').scrollWidth <= document.querySelector('.topology-viewport').clientWidth + 1"
    )
    page.set_viewport_size({"width": 1440, "height": 1000})
    node("Edge-02").focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog")).to_be_visible()
    assert not errors, errors
    print(
        json.dumps(
            {
                "topology": "PASS",
                "stable_sidebar_zoom_cases": 18,
                "sizes": [1440, 375, 812],
                "themes": ["dark", "light"],
                "errors": errors,
            }
        )
    )
    browser.close()
