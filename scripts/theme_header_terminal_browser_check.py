"""Scrolled theme headers and full terminal buffers, using isolated HTTP and mocked SSH.

Run with scripts.user_workspace_fixture on loopback port 8241; never contacts devices.
"""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
OUT = Path("artifacts/theme-header-terminal")
OUT.mkdir(parents=True, exist_ok=True)
DESIGNS = ("atlas", "orbit", "terminal", "panorama", "focus")
PALETTES = ("cobalt", "teal", "violet", "amber", "forest", "slate", "rose", "cyan", "orange", "indigo")
SIZES = ((1440, 1000), (1024, 768), (768, 1024), (375, 812))
errors, frames, reports = [], [], []
connections = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(reduced_motion="reduce", bypass_csp=True)
    context.route_web_socket("**/api/v1/ws", lambda ws: None)

    def ssh(ws):
        global connections
        connections += 1
        ws.send(json.dumps({"type": "status", "status": "connected"}))
        ws.send(
            json.dumps(
                {
                    "type": "output",
                    "data": "".join(f"Buffer line {n}\r\n" for n in range(120)) + "SW-01# ",
                }
            )
        )

        def message(raw):
            value = json.loads(raw)
            frames.append(value)
            if value["type"] == "input":
                ws.send(json.dumps({"type": "output", "data": value["data"]}))

        ws.on_message(message)

    context.route_web_socket("**/api/v1/access/sessions/*/ws", ssh)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def settle():
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    header_checks = 0
    for design in DESIGNS:
        for mode in ("dark", "light"):
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                for palette in PALETTES:
                    page.evaluate(
                        "v => Object.assign(document.documentElement.dataset,v)",
                        {
                            "design": design,
                            "theme": mode,
                            "palette": palette,
                        },
                    )
                    page.evaluate("scrollTo(0, 600)")
                    settle()
                    state = page.evaluate("""() => {
                      const region = document.querySelector('.topbar-region');
                      const r = region.getBoundingClientRect();
                      const header = document.querySelector('.topbar').getBoundingClientRect();
                      const bg = getComputedStyle(region).backgroundColor;
                      const points = [[r.left+2,r.top+2],[r.right-2,r.top+2],
                        [r.left+2,r.bottom-2],[r.right-2,r.bottom-2],
                        [header.left+header.width/2,header.top+2]];
                      return {top:r.top,bottom:r.bottom,headerTop:header.top,scroll:scrollY,bg,
                        covered:points.every(([x,y]) => region.contains(document.elementFromPoint(x,y))),
                        overflow:document.body.scrollWidth>innerWidth};
                    }""")
                    key = f"{design}-{mode}-{width}-{palette}"
                    assert state["scroll"] > 100, (key, state)
                    assert state["covered"] and not state["overflow"], (key, state)
                    assert state["bg"].startswith("rgb("), (key, state)
                    assert state["top"] == (146 if design == "panorama" and width >= 1280 else 0), (
                        key,
                        state,
                    )
                    header_checks += 1
                if width in (1440, 375):
                    page.screenshot(path=str(OUT / f"header-{design}-{mode}-{width}.png"))
    page.set_viewport_size({"width": 1440, "height": 1000})
    device = context.request.get(BASE + "/api/v1/access/devices").json()["items"][0]
    page.evaluate("d => window.dispatchEvent(new CustomEvent('netrix:ssh-open',{detail:d}))", device)
    terminal = page.locator(".ssh-dialog[open]")
    expect(terminal.locator(".xterm-rows")).to_contain_text("SW-01#")

    def terminal_geometry(key):
        # ResizeObserver + FitAddon settle asynchronously after opening Aa or changing fonts.
        page.wait_for_function(
            """() => {
          const host=document.querySelector('.ssh-terminal');
          const screen=document.querySelector('.xterm-screen');
          const cursor=document.querySelector('.xterm-cursor');
          if(!host || !screen || !cursor) return false;
          const h=host.getBoundingClientRect(),s=screen.getBoundingClientRect(),c=cursor.getBoundingClientRect();
          const style=getComputedStyle(host);
          return s.left>=h.left+parseFloat(style.paddingLeft)-1 &&
            s.right<=h.right-parseFloat(style.paddingRight)+1 &&
            s.bottom<=h.bottom-parseFloat(style.paddingBottom)+1 &&
            c.top>=s.top-1 && c.bottom<=s.bottom+1;
        }""",
            timeout=5000,
        )
        assert terminal.evaluate("e => e.scrollWidth <= e.clientWidth"), key
        assert terminal.locator(".ssh-footer").evaluate(
            "e => e.getBoundingClientRect().bottom <= innerHeight+1"
        ), key
        page.screenshot(path=str(OUT / f"terminal-{key}.png"))
        reports.append(key)

    for design in DESIGNS:
        for mode in ("dark", "light"):
            page.evaluate(
                "v => Object.assign(document.documentElement.dataset,v)",
                {
                    "design": design,
                    "theme": mode,
                    "palette": "violet",
                },
            )
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                key = f"{design}-{mode}-{width}"
                terminal_geometry(key + "-closed")
                terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
                terminal_geometry(key + "-open")
                terminal.get_by_label("Yazı boyutu", exact=True).select_option("22")
                page.wait_for_function(
                    "() => getComputedStyle(document.querySelector('.xterm-rows')).fontSize==='22px'"
                )
                terminal_geometry(key + "-font")
                terminal.get_by_role("button", name="Vazgeç", exact=True).click()
                page.wait_for_function(
                    "() => getComputedStyle(document.querySelector('.xterm-rows')).fontSize==='15px'"
                )
                terminal_geometry(key + "-restored")
    # A typed command remains on the active line through repeated appearance changes.
    terminal.locator(".xterm-helper-textarea").focus()
    page.keyboard.type("show version")
    expect(terminal.locator(".xterm-rows")).to_contain_text("SW-01# show version")
    terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
    terminal_geometry("typed-command-open")
    expect(terminal.locator(".xterm-rows")).to_contain_text("SW-01# show version")
    terminal.get_by_role("button", name="Vazgeç", exact=True).click()
    terminal_geometry("typed-command-closed")
    expect(terminal.locator(".xterm-rows")).to_contain_text("SW-01# show version")
    assert connections == 1, connections
    assert not errors, errors
    report = {
        "header_checks": header_checks,
        "terminal_checks": len(reports),
        "connections": connections,
        "errors": errors,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    browser.close()
