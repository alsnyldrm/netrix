"""Verify the widget layout and interactions without any live network or inventory requests."""

import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8219")
WHEN = "2026-11-14T09:00:00Z"
DAILY = [{"day": (date(2026, 11, 8) + timedelta(days=i)).isoformat(), "count": count}
         for i, count in enumerate((2, 9, 4, 0, 14, 6, 10))]
WIDGETS = {"charts": {
               "daily": {"jobs": DAILY, "backups": DAILY, "alarms": DAILY},
               "device_types": [{"label": "Switch", "count": 9}],
               "firmware": {"queued": 5, "succeeded": 15},
               "vlan_problems": [{"label": "Laboratuvar · VLAN 30 · default", "count": 3}],
           },"counts": {"scopes": 0, "rules": 1, "no_backup": 2, "ip_problems": 3, "links": 14, "unverified": 2, "ip_resolved": 7, "alarm_critical": 1,
                      "alarm_warning": 0, "alarm_info": 0, "succeeded": 24, "partial": 3, "failed": 2},
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
            "access/preferences": {"palette": "violet"},
        }.get(path, {"items": [], "total": 0})
        route.fulfill(json=response)

    page.add_init_script(f"localStorage.setItem('netrix-theme', '{theme}')")
    if theme == "dark":
        page.add_init_script("""if (!localStorage.getItem('netrix-overview-v1:overview-fixture')) {
           localStorage.setItem('netrix-overview-v1:overview-fixture', JSON.stringify(
             ['alarms', 'gaps', 'inventory', 'ipam', 'backups', 'jobs', 'firmware', 'system', 'events']
           ));
        }""")
    page.route("**/api/v1/**", fixture)
    page.goto(BASE + "/#overview")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Genel bakış", exact=True)).to_be_visible()
    expect(page.get_by_text("Konfigürasyon değişikliği algılandı", exact=True)).to_be_visible()
    expect(page.get_by_text("Yanıt yok", exact=True)).to_be_visible()
    expect(page.locator(".overview-chart")).to_have_count(10)
    assert not any(path.split("/")[0] in {"devices", "links", "topology"} for path in requests)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.wait_for_function("""() => !document.querySelector('.overview-workspace')
        .getAnimations({subtree: true}).some(animation => animation.playState === 'running')""")
    page.add_script_tag(path="frontend/node_modules/axe-core/axe.min.js")
    violations = page.evaluate("async () => (await axe.run('.overview-workspace')).violations")
    assert not violations, [(item["id"], [(node["target"], node["failureSummary"]) for node in item["nodes"]]) for item in violations]
    alignment = page.locator("[data-overview-widget] header").evaluate_all(
        """headers => headers.every(header => {
          const [icon, title] = header.children;
          const a = icon.getBoundingClientRect();
          const b = title.getBoundingClientRect();
          return Math.abs(a.top + a.height / 2 - b.top - b.height / 2) < 1.1;
        })"""
    )
    assert alignment
    chart = page.locator(".overview-trend").first
    plot = chart.locator("svg").bounding_box()
    chart_box = chart.bounding_box()
    assert plot["width"] >= chart_box["width"] - 1 and plot["height"] >= 110
    first_card = page.locator("[data-overview-widget]").first
    assert first_card.locator("header").bounding_box()["height"] <= 54
    toolbar = page.locator(".overview-command")
    expect(toolbar.get_by_text("Son veri", exact=False)).to_be_visible()
    edit_button = toolbar.get_by_role("button", name="Yerleşimi düzenle", exact=True)
    add_button = toolbar.get_by_role("button", name="Widget ekle", exact=True)
    edit_box, add_box = edit_button.bounding_box(), add_button.bounding_box()
    assert abs(edit_box["y"] - add_box["y"]) < 1
    assert abs(edit_box["height"] - add_box["height"]) < 1
    edit_icon = edit_button.locator("svg").bounding_box()
    edit_label = edit_button.locator("span").bounding_box()
    assert abs(edit_icon["y"] + edit_icon["height"] / 2 - edit_label["y"] - edit_label["height"] / 2) < 1
    if mobile:
        assert abs(edit_box["width"] - add_box["width"]) < 1
    else:
        title_box = toolbar.locator(".overview-command-title").bounding_box()
        assert abs(title_box["y"] + title_box["height"] / 2 - edit_box["y"] - edit_box["height"] / 2) < 1
    expect(page.locator(".overview-edit-hint")).to_have_count(0)
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

    grip = page.get_by_role("button", name="Aktif alarmlar sürükle", exact=True)
    grip.scroll_into_view_if_needed()
    source = grip.bounding_box()
    x, y = source["x"] + 22, source["y"] + 22
    destination = card.nth(1)
    target = destination.bounding_box()
    tx = target["x"] + 55
    ty = min(target["y"] + 70, page.viewport_size["height"] - 15)
    if mobile:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        # Holding the pointer at the bottom must scroll even without another move.
        edge = page.viewport_size["height"] - 12
        original_scroll = page.evaluate("scrollY")
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": tx, "y": edge}]})
        page.wait_for_function("(start) => scrollY > start + 50", arg=original_scroll)
        target = destination.bounding_box()
        ty = min(target["y"] + 80, page.viewport_size["height"] - 105)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": tx, "y": ty}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    else:
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(tx, ty, steps=10)
        expect(page.locator(".overview-drag-preview")).to_be_visible()
        expect(destination).to_have_class("panel overview-widget overview-drop-target")
        page.mouse.up()
    expect(card.first).to_have_attribute("data-overview-widget", "gaps")
    expect(page.get_by_role("button", name="Yerleşimi düzenle", exact=True)).to_be_visible()
    edit_button.click()
    expect(page.locator(".overview-edit-hint")).to_be_visible()
    page.get_by_role("button", name="Aktif alarmlar yukarı taşı", exact=True).press("Enter")
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
                    has_touch=mobile,
                )
                verify(page, mobile, theme)
                page.context.close()
        browser.close()
    print("Overview widget interactions passed on desktop and mobile.")
