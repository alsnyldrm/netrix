"""Verify the widget layout and interactions without any live network or inventory requests."""

import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8219")
WHEN = "2026-11-14T09:00:00Z"
WIDGETS = {"counts": {"scopes": 0, "rules": 1, "no_backup": 2, "ip_problems": 3, "links": 14},
           "alerts": [{"id": "1", "message": "Konfigürasyon değişikliği algılandı",
                       "severity": "critical", "created_at": WHEN, "acknowledged_at": None}],
           "events": [{"id": "2", "message": "Konfigürasyon yedeği tamamlandı", "created_at": WHEN}],
           "server_time": WHEN}


def verify(page, mobile, theme):
    requests, errors = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route_web_socket("**/api/v1/ws", lambda _: None)

    def fixture(route):
        path = urlparse(route.request.url).path.removeprefix("/api/v1/")
        requests.append(path)
        response = {
            "auth/me": {"id": "overview-fixture", "display_name": "Test", "role": "viewer"},
            "dashboard": {"counts": {"firing_alerts": 1, "active_devices": 10, "reachable": 8},
                          "server_time": WHEN},
            "dashboard/widgets": WIDGETS,
            "system": {"database": "postgresql", "redis": "ok", "worker": WHEN, "scheduler": None},
            "access/preferences": {},
        }.get(path, {"items": [], "total": 0})
        route.fulfill(json=response)

    page.add_init_script(f"localStorage.setItem('netrix-theme', '{theme}')")
    page.route("**/api/v1/**", fixture)
    page.goto(BASE + "/#overview")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Genel bakış", exact=True)).to_be_visible()
    expect(page.get_by_text("Konfigürasyon değişikliği algılandı", exact=True)).to_be_visible()
    expect(page.get_by_text("Yanıt yok", exact=True)).to_be_visible()
    assert not any(path.split("/")[0] in {"devices", "links", "topology"} for path in requests)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.add_script_tag(path="frontend/node_modules/axe-core/axe.min.js")
    violations = page.evaluate("async () => (await axe.run('.overview-workspace')).violations")
    assert not violations, [(item["id"], [node["target"] for node in item["nodes"]]) for item in violations]
    alignment = page.locator("[data-overview-widget] header").evaluate_all(
        """headers => headers.every(header => {
          const [icon, title] = header.children;
          const a = icon.getBoundingClientRect();
          const b = title.getBoundingClientRect();
          return Math.abs(a.top + a.height / 2 - b.top - b.height / 2) < 1.1;
        })"""
    )
    assert alignment
    if output := os.environ.get("NETRIX_OVERVIEW_SCREENSHOTS"):
        page.screenshot(path=str(Path(output) / f"overview-{'mobile' if mobile else 'desktop'}-{theme}.png"), full_page=True)

    card = page.locator("[data-overview-widget]")
    button = page.get_by_role("button", name="Widget ekle", exact=True)
    button.click()
    dialog = page.get_by_role("dialog", name="Widget kataloğu")
    dialog.get_by_role("button", name="Ekle · IPAM kaynakları", exact=True).click()
    expect(dialog.get_by_role("button", name="Eklendi · IPAM kaynakları", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")
    expect(button).to_be_focused()
    expect(card.last).to_have_attribute("data-overview-widget", "integrations")

    page.get_by_role("button", name="Yerleşimi düzenle", exact=True).click()
    page.get_by_role("button", name="Aktif alarmlar aşağı taşı", exact=True).press("Enter")
    expect(card.first).to_have_attribute("data-overview-widget", "gaps")

    grip = page.get_by_role("button", name="Eksikler ve inceleme sürükle", exact=True)
    grip.scroll_into_view_if_needed()
    if mobile:
        # Fit two cards into the viewport so the touch drag has a visible destination.
        page.locator(".overview-widget-body").evaluate_all("(items) => items.forEach(i => i.hidden = true)")
    source = grip.bounding_box()
    target = card.nth(1).locator("header").bounding_box()
    x, y = source["x"] + 20, source["y"] + 20
    tx, ty = target["x"] + 32, target["y"] + 22
    if mobile:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": tx, "y": ty}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    else:
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(tx, ty, steps=10)
        page.mouse.up()
    expect(card.first).to_have_attribute("data-overview-widget", "alarms")

    page.get_by_role("button", name="Son hareketler kaldır", exact=True).click()
    expect(page.get_by_role("heading", name="Son hareketler", exact=True)).to_have_count(0)
    page.reload()
    expect(card.first).to_have_attribute("data-overview-widget", "alarms")
    expect(card.last).to_have_attribute("data-overview-widget", "integrations")
    expect(page.get_by_role("heading", name="Son hareketler", exact=True)).to_have_count(0)
    assert not errors, errors


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height, mobile in ((1440, 1000, False), (390, 844, True)):
            for theme in ("light", "dark"):
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    has_touch=mobile, reduced_motion="reduce",
                )
                verify(page, mobile, theme)
                page.context.close()
        browser.close()
    print("Overview widget interactions passed on desktop and mobile.")
