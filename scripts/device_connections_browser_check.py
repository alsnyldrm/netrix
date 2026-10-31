"""Real local API: uplinks, both port ends, retry, navigation, layout and accessibility."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8238")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("HP-SW-CO-01-B-05-02")
    page.get_by_role("button", name="HP-SW-CO-01-B-05-02", exact=True).click()
    section = page.get_by_role("region", name="Üst akış bağlantıları")
    cards = section.locator(":scope > .connection-cards > li")
    expect(cards).to_have_count(1)
    expect(cards.first.locator(".connection-endpoints > div").nth(0)).to_contain_text("Trk1")
    expect(cards.first.locator(".connection-endpoints > div").nth(2)).to_contain_text("Trk7")
    expect(cards.first).to_contain_text("CDP + LLDP")
    expect(section).to_contain_text("%65 güven")
    expect(cards.first.locator(".connection-members li")).to_have_count(2)
    expect(cards.first.locator(".connection-members")).to_contain_text("A1")
    expect(cards.first.locator(".connection-members")).to_contain_text("I4")
    expect(cards.first.locator(".connection-members")).to_contain_text("B1")
    expect(cards.first.locator(".connection-members")).to_contain_text("D2")
    expect(section).not_to_contain_text("Unresolved-neighbor")
    expect(section).not_to_contain_text("Diğer komşu bağlantıları")
    Path("artifacts").mkdir(exist_ok=True)
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            section.evaluate("e=>e.scrollIntoView({block:'start'})")
            page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            dialog = page.get_by_role("dialog")
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            boxes = cards.first.locator(".connection-endpoints > div").evaluate_all(
                "es=>es.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y}})"
            )
            axis = "y" if width > 640 else "x"
            assert max(b[axis] for b in boxes) - min(b[axis] for b in boxes) <= 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            page.screenshot(path=f"artifacts/device-connections-{width}-{theme}.png")
    # Keyboard opens the peer in the same modal and refreshes both endpoints.
    peer = cards.first.get_by_role("button", name="HP-SW-BB-01-A-00-01", exact=True)
    peer.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog", name="HP-SW-BB-01-A-00-01", exact=True)).to_be_visible()
    expect(section).to_contain_text("Üst akış bağlantısı henüz belirlenemedi")
    expect(section).not_to_contain_text("Alt bağlantı adayı")
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Fixture 02")
    page.route(
        "**/devices/*/connections",
        lambda r: r.fulfill(status=503, json={"detail": "Fixture failure"}),
        times=1,
    )
    page.get_by_role("button", name="Fixture 02", exact=True).click()
    expect(section.get_by_role("alert")).to_contain_text("güncellenemedi")
    section.get_by_role("button", name="Tekrar dene", exact=True).click()
    expect(section).to_contain_text("Üst akış bağlantısı henüz belirlenemedi")
    expect(section.get_by_role("alert")).to_have_count(0)
    page.keyboard.press("Escape")
    page.goto(BASE + "/#neighbors")
    page.wait_for_load_state("networkidle")
    select = page.get_by_label("Bağlantı ayrıntısı", exact=True)
    select.select_option(index=1)
    detail = page.locator(".topology-link-detail")
    expect(detail).to_contain_text("I4")
    expect(detail).to_contain_text("A1")
    expect(detail).to_contain_text("D2")
    expect(detail).to_contain_text("B1")
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            detail.scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert detail.evaluate("e=>e.scrollWidth<=e.clientWidth")
            assert select.bounding_box()["height"] >= 44
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"map-{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
            )
            page.screenshot(path=f"artifacts/neighbor-detail-map-{width}-{theme}.png")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(json.dumps({"connections": "PASS", "axe": reports, "console_errors": errors}))
    browser.close()
