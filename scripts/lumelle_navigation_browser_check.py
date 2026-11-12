"""Check real navigation motion with the local user_workspace fixture and Chromium."""

import os

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8289")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True, executable_path=os.environ.get("NETRIX_CHROMIUM")
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 900}, reduced_motion="no-preference"
    )
    context.route_web_socket("**/api/v1/ws", lambda socket: None)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/#overview")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    root = page.locator("html")
    view = page.locator(".page-view")
    sidebar = page.get_by_role("navigation", name="Sayfalar", exact=True)
    expect(view).to_have_attribute("data-page", "overview")
    page.evaluate("document.fonts.ready")
    page.evaluate("""() => {
        window.pageEntrances = [];
        document.addEventListener('animationstart', event => {
            if (event.target.matches?.('.page-view') && !event.pseudoElement)
                window.pageEntrances.push(event.target.dataset.page);
        });
    }""")

    inventory = sidebar.get_by_role("button", name="Envanter", exact=True)
    submenu = page.locator("#" + inventory.get_attribute("aria-controls"))
    expect(submenu).to_have_attribute("inert", "")
    inventory.press("Enter")
    expect(inventory).to_have_attribute("aria-expanded", "true")
    page.wait_for_function(
        """() => Array.from(document.querySelector('[data-open=true]').getAnimations())
            .some(a => a.transitionProperty === 'grid-template-rows' && a.playState === 'running')"""
    )
    expect(submenu).not_to_have_attribute("inert", "")
    sidebar.get_by_role("button", name="Cihaz envanteri", exact=True).click()
    expect(root).to_have_attribute("data-route-motion", "forward")
    expect(view).to_have_attribute("data-page", "devices")
    page.wait_for_function(
        """() => document.getAnimations().some(a => a.animationName === 'lumelle-page-exit')
            && document.getAnimations().some(a => a.animationName === 'lumelle-page-enter')"""
    )
    assert page.evaluate("""() => {
        const exit = document.getAnimations().find(a => a.animationName === 'lumelle-page-exit');
        const enter = document.getAnimations().find(a => a.animationName === 'lumelle-page-enter');
        return exit.effect.getTiming().duration === 280
            && enter.effect.getTiming().duration === 600
            && enter.effect.getTiming().delay === 280;
    }""")
    page.wait_for_function(
        """() => document.querySelector('.nav-active-marker').getAnimations()
            .some(a => a.transitionProperty === 'transform')"""
    )
    page.wait_for_function("() => !document.documentElement.dataset.routeMotion")
    expect(view).to_have_css("animation-name", "none")
    page.go_back()
    expect(root).to_have_attribute("data-route-motion", "backward")
    expect(view).to_have_attribute("data-page", "overview")
    page.wait_for_function("() => !document.documentElement.dataset.routeMotion")
    expect(view).to_have_css("animation-name", "none")
    expect(submenu).to_have_attribute("data-open", "false")
    expect(submenu).to_have_css("visibility", "hidden")
    page.get_by_role("button", name="Menüyü daralt", exact=True).click()
    page.wait_for_function(
        """() => document.querySelector('.app-shell').getAnimations()
            .some(a => a.transitionProperty === 'grid-template-columns')"""
    )
    page.get_by_role("button", name="Menüyü genişlet", exact=True).click()

    page.set_viewport_size({"width": 375, "height": 812})
    dock = page.get_by_role("navigation", name="Hızlı gezinme", exact=True)
    dock.get_by_role("button", name="VLAN", exact=True).click()
    expect(view).to_have_attribute("data-page", "vlans")
    page.wait_for_function(
        """() => document.querySelector('.dock-active-marker').getAnimations()
            .some(a => a.transitionProperty === 'transform')"""
    )
    page.wait_for_function("() => !document.documentElement.dataset.routeMotion")
    page.get_by_role("button", name="Hesap ayarlarını aç", exact=True).click()
    profile = page.get_by_role("dialog", name="Profil", exact=True)
    profile.get_by_role("button", name="Renk paleti", exact=True).click()
    assert profile.locator(".profile-content").evaluate("el => el.getAnimations().length") == 1
    page.keyboard.press("Escape")

    page.emulate_media(reduced_motion="reduce")
    dock.get_by_role("button", name="Görevler", exact=True).click()
    expect(view).to_have_attribute("data-page", "jobs")
    expect(root).not_to_have_attribute("data-route-motion", "forward")
    expect(view).to_have_css("animation-name", "none")

    page.emulate_media(reduced_motion="no-preference")
    page.evaluate("() => document.startViewTransition = undefined")
    dock.get_by_role("button", name="Başlangıç", exact=True).click()
    expect(view).to_have_attribute("data-page", "overview")
    expect(view).to_have_css("animation-name", "lumelle-page-enter")
    page.wait_for_function("() => window.pageEntrances.length > 0")
    assert page.evaluate("window.pageEntrances") == ["overview"]
    assert not errors, errors
    print("PASS: one page transition, paced exit and entrance, history, mobile, profile and motion fallback")
