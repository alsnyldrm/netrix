"""Lumelle motion, route interruption and accessibility against the local fixture."""
import json
import os
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8294")
out = Path(os.environ.get("NETRIX_MOTION_ARTIFACTS", "/tmp/netrix-lumelle-motion"))
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("NETRIX_CHROMIUM"))
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="no-preference")
    context.route_web_socket("**/api/v1/ws", lambda socket: None)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""(() => {
      window.motionLog = [];
      const animate = Element.prototype.animate;
      Element.prototype.animate = function(frames, options) {
        const a = animate.call(this, frames, options);
        queueMicrotask(() => motionLog.push({id: a.id, page: this.closest('.page-view')?.dataset.page,
          duration: options.duration, delay: options.delay, frames,
          text: this.textContent?.slice(0,50), element: this.className}));
        return a;
      };
    })()""")
    page.goto(base + "/#overview")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    view = page.locator(".page-view")
    sidebar = page.get_by_role("navigation", name="Sayfalar", exact=True)
    expect(view).to_have_attribute("data-page", "overview")
    page.evaluate("document.fonts.ready")

    def settled():
        page.wait_for_function("() => !document.getAnimations().some(a => a.id.startsWith('lumelle-') && a.playState === 'running')")

    def route(key):
        expect(view).to_have_attribute("data-page", key)
        settled()
        expect(view).to_have_css("transform", "none")
        assert page.evaluate("document.documentElement.dataset.routeMotion") is None

    settled()
    assert page.evaluate("motionLog.some(a => a.id === 'lumelle-chrome-enter' && a.duration === 800)")
    page.evaluate("motionLog = []")
    sidebar.get_by_role("button", name="Envanter", exact=True).click()
    expect(view).to_have_attribute("data-page", "devices")
    expect(page.get_by_role("heading", name="Cihaz envanteri", exact=True)).to_be_visible()
    page.screenshot(path=out / "desktop-in-motion.png")
    route("devices")
    log = page.evaluate("motionLog")
    assert sum(a["id"] == "lumelle-page-enter" for a in log) == 1, log
    assert next(a for a in log if a["id"] == "lumelle-page-exit")["duration"] == 180
    assert next(a for a in log if a["id"] == "lumelle-page-enter")["duration"] == 700
    title = [a for a in log if a["id"] == "lumelle-title"]
    assert len(title) == len("Cihazenvanteri"), title
    assert all(a["duration"] == 850 and a["delay"] == i * 22 for i, a in enumerate(title))
    assert any(a["id"] == "lumelle-card-enter" and a["duration"] == 800 for a in log)
    assert any(a["id"] == "lumelle-menu-label" and a["duration"] == 400 and a["delay"] == 80 for a in log)
    assert any(a["id"] == "lumelle-nav-marker" and a["duration"] == 550 for a in log)
    assert any(a["id"] == "lumelle-row-enter" and a["duration"] == 550 for a in log)
    assert page.locator(".page-heading h1").inner_text() == "Cihaz envanteri"
    page.screenshot(path=out / "desktop.png")

    # Same-page changes and live data refresh must not cause a second entrance.
    page.evaluate("motionLog = []")
    sidebar.get_by_role("button", name="Cihaz envanteri", exact=True).click()
    page.keyboard.press("Control+k")
    page.get_by_role("button", name="Açık sayfayı yenile", exact=False).click()
    page.wait_for_timeout(1000)
    assert not page.evaluate("motionLog.some(a => ['lumelle-page-enter', 'lumelle-title', 'lumelle-row-enter'].includes(a.id))")

    # A later click wins, even before the 180ms exit has finished.
    page.evaluate("motionLog = []")
    sidebar.get_by_role("button", name="IP adres yönetimi", exact=True).evaluate("el => el.click()")
    sidebar.get_by_role("button", name="Konfigürasyon", exact=True).evaluate("el => el.click()")
    route("configuration")
    assert [a["page"] for a in page.evaluate("motionLog") if a["id"] == "lumelle-page-enter"] == ["configuration"]
    page.go_back()
    route("devices")
    page.go_forward()
    route("configuration")
    # Return to the displayed route before the outgoing history transition commits.
    page.evaluate("location.hash = 'devices'")
    page.wait_for_function("document.documentElement.dataset.routeMotion === 'backward'")
    page.evaluate("location.hash = 'configuration'")
    route("configuration")
    assert page.url.endswith("#configuration")

    page.get_by_role("button", name="Menüyü daralt", exact=True).click()
    page.wait_for_function("document.querySelector('.app-shell').dataset.sidebarMotion === 'collapse'")
    page.screenshot(path=out / "sidebar-collapse.png")
    expect(page.locator(".app-shell")).to_have_class("app-shell collapsed")
    settled()
    assert page.locator(".sidebar").bounding_box()["width"] == 84
    assert page.locator(".app-shell").get_attribute("data-sidebar-motion") is None
    page.get_by_role("button", name="Menüyü genişlet", exact=True).click()
    page.screenshot(path=out / "sidebar-expand.png")
    settled()
    assert page.locator(".sidebar").bounding_box()["width"] > 200
    assert page.locator(".app-shell").get_attribute("data-sidebar-motion") is None
    # Resizing during a fold must release temporary widths and clipping.
    page.get_by_role("button", name="Menüyü daralt", exact=True).evaluate("el => el.click()")
    page.set_viewport_size({"width": 1024, "height": 768})
    settled()
    assert page.locator(".app-shell").get_attribute("data-sidebar-motion") is None
    assert page.locator(".sidebar").evaluate("el => el.style.width") == ""
    page.get_by_role("button", name="Menüyü genişlet", exact=True).click()
    settled()

    page.set_viewport_size({"width": 375, "height": 812})
    dock = page.get_by_role("navigation", name="Hızlı gezinme", exact=True)
    dock.get_by_role("button", name="VLAN", exact=True).click()
    route("vlans")
    page.screenshot(path=out / "mobile.png")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="Menüyü aç", exact=True).click()
    expect(page.locator(".sidebar")).to_be_visible()
    settled()
    page.screenshot(path=out / "mobile-sidebar.png")
    page.get_by_role("button", name="Menüyü kapat", exact=True).click()
    page.set_viewport_size({"width": 812, "height": 375})
    settled()
    page.screenshot(path=out / "landscape.png")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size({"width": 375, "height": 812})

    page.emulate_media(reduced_motion="reduce")
    page.evaluate("motionLog = []")
    dock.get_by_role("button", name="Görevler", exact=True).click()
    route("jobs")
    assert not page.evaluate("motionLog.some(a => a.id.startsWith('lumelle-'))")
    page.emulate_media(reduced_motion="no-preference")
    page.evaluate("document.documentElement.dataset.reduceMotion = 'true'")
    dock.get_by_role("button", name="Başlangıç", exact=True).click()
    route("overview")
    assert not page.evaluate("motionLog.some(a => a.id.startsWith('lumelle-'))")

    # Motion does not depend on the optional View Transition browser API.
    page.evaluate("document.documentElement.dataset.reduceMotion = 'false'; document.startViewTransition = undefined; motionLog = []")
    dock.get_by_role("button", name="VLAN", exact=True).click()
    route("vlans")
    assert sum(a["id"] == "lumelle-page-enter" for a in page.evaluate("motionLog")) == 1
    assert page.locator("h1 .motion-char").count() > 0
    assert not errors, errors
    (out / "implementation-motion.json").write_text(json.dumps(log, indent=2, ensure_ascii=False))
    browser.close()
    print("PASS: measured title/card/sidebar motion, one route entrance, rapid navigation, history, desktop/mobile/landscape and both reduced-motion preferences")
