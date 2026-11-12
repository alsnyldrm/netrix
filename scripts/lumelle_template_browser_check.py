"""Verify template navigation and overlays with the isolated NETRIX workspace fixture."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8289")
screens = os.environ.get("NETRIX_SCREENSHOTS")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True, executable_path=os.environ.get("NETRIX_CHROMIUM")
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="no-preference", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda socket: None)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/#overview")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_function("document.querySelector('.page-view')?.dataset.page === 'overview'")
    page.evaluate("document.fonts.ready")

    def screenshot(name):
        if screens:
            output = Path(screens)
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / f"{name}.png"))

    sidebar = page.get_by_role("complementary", name="Ana menü", exact=True)
    account = page.get_by_role("button", name="Hesap menüsü", exact=True)
    notices = page.get_by_role("button", name="Bildirimler", exact=True)
    create = page.get_by_role("button", name="Yeni", exact=True)
    expect(sidebar.get_by_role("button", name="Profil", exact=True)).to_have_count(0)
    expect(sidebar.get_by_role("button", name="Güvenli çıkış", exact=True)).to_have_count(0)
    expect(sidebar.locator(".avatar")).to_have_count(0)
    expect(page.locator(".topbar-refresh")).to_have_count(0)
    screenshot("overview-desktop")

    for width, height in ((1440, 1000), (1024, 768), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        for trigger, menu_id in (
            (account, "lumelle-account"), (create, "lumelle-create"), (notices, "lumelle-notices")
        ):
            trigger.click()
            panel = page.locator("#" + menu_id)
            expect(trigger).to_have_attribute("aria-expanded", "true")
            page.wait_for_function(
                """id => document.getElementById(id).getAnimations().some(
                    a => a.transitionProperty === 'transform' && a.effect.getTiming().duration === 440
                )""",
                arg=menu_id,
            )
            expect(panel).to_have_css("transform", "none")
            if menu_id == "lumelle-notices":
                expect(panel.get_by_text("Bildirim yok.", exact=True)).to_be_visible()
            bounds = panel.bounding_box()
            assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width, (menu_id, bounds)
            screenshot(f"{menu_id}-{width}")
            page.keyboard.press("Escape")
            expect(trigger).to_have_attribute("aria-expanded", "false")
            expect(trigger).to_be_focused()

    create.click()
    page.get_by_role("region", name="Yeni kayıt", exact=True).get_by_role(
        "button", name="Cihaz", exact=True
    ).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    account.click()
    page.get_by_role("button", name="Profil", exact=True).click()
    expect(page.get_by_role("dialog", name="Profil", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(account).to_be_focused()

    page.get_by_role("button", name="Diğer", exact=True).click()
    expect(sidebar.locator(".lumelle-drawer-shortcuts button")).to_have_count(3)
    expect(sidebar.get_by_role("button", name="Firmware deposu", exact=True)).to_be_visible()
    screenshot("more-mobile")
    sidebar.get_by_role("button", name="Firmware deposu", exact=True).click()
    expect(page.locator(".page-view")).to_have_attribute("data-page", "firmware-images")
    expect(sidebar).to_be_hidden()
    expect(page.get_by_role("navigation", name="Firmware sayfaları")).to_be_visible()
    page.wait_for_function("() => !document.documentElement.dataset.routeMotion")

    account.click()
    page.get_by_role("button", name="Açık", exact=True).click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.wait_for_function(
        """() => document.getAnimations().some(a =>
            a.animationName === 'lumelle-theme-reveal' && a.effect.getTiming().duration === 450
        )"""
    )
    page.wait_for_function("() => !document.documentElement.dataset.themeMotion")
    assert page.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
    screenshot("firmware-light-mobile")
    assert not errors, errors
    print("PASS: no sidebar account, three animated toolbar menus, mobile sheet, routed tabs and theme reveal")
