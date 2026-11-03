"""Verify read-only navigation, pushed/fallback ICMP updates and schedule-only UI."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8237"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    sockets, collectors, errors = [], [], []
    page.route_web_socket("**/api/v1/ws", lambda socket: sockets.append(socket))
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: (
            collectors.append(request.url)
            if request.method == "POST" and (request.url.endswith(("/discover", "/ping", "/sync")))
            else None
        ),
    )
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    target = page.get_by_role("row").filter(has=page.get_by_role("button", name="192.0.2.12", exact=True))
    expect(target.locator(".ipam-state")).to_have_text("Pasif")
    expect(page.get_by_role("button", name="Tara", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Ping", exact=True)).to_have_count(0)
    expect(page.get_by_text("Ping: 30 sn", exact=True)).to_be_visible()
    result = page.request.post(
        BASE + "/fixture/ping-result?reachable=true", headers={"X-Netrix-Request": "1"}
    ).json()
    assert sockets
    sockets[-1].send(json.dumps({"type": "ipam_ping", "vlan_id": result["vlan_id"]}))
    expect(target.locator(".ipam-state")).to_have_text("Aktif", timeout=3000)
    page.get_by_role("button", name="192.0.2.12", exact=True).click()
    dialog = page.get_by_role("dialog")
    ping = (
        dialog.locator(".ipam-summary > div").filter(has=page.locator("dt", has_text="Ping")).locator("dd")
    )
    expect(ping).to_have_text("Yanıt var")
    page.request.post(BASE + "/fixture/ping-result?reachable=false", headers={"X-Netrix-Request": "1"})
    sockets[-1].send(json.dumps({"type": "ipam_ping", "vlan_id": result["vlan_id"]}))
    expect(ping).to_have_text("Yanıt yok", timeout=3000)
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    expect(target.locator(".ipam-state")).to_have_text("Pasif")
    # No socket event: the local DB fallback still updates the open view.
    page.request.post(BASE + "/fixture/ping-result?reachable=true", headers={"X-Netrix-Request": "1"})
    expect(target.locator(".ipam-state")).to_have_text("Aktif", timeout=12000)
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
            page.evaluate("window.scrollTo(0,0)")
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))"
            )
            page.screenshot(path=f"/tmp/netrix-scheduled-vlan-{width}-{theme}.png")
    assert not collectors, collectors
    assert not errors, errors
    print(
        "PASS: no scan on navigation, no manual collection actions, pushed active/passive status in list and detail, DB fallback, desktop/mobile/landscape and axe"
    )
    browser.close()
