"""Real HTTP preferences/commands and mocked SSH: terminal controls, geometry and accessibility."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
OUT = Path("artifacts/terminal-controls")
OUT.mkdir(parents=True, exist_ok=True)
errors, violations, frames = [], {}, []
connections = 0
writes = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)

    def ssh(ws):
        global connections
        connections += 1
        ws.send(json.dumps({"type": "status", "status": "connected"}))
        ws.send(json.dumps({"type": "output", "data": "NETRIX terminal fixture\r\nSW-01# "}))

        def message(raw):
            value = json.loads(raw)
            frames.append(value)
            if value["type"] == "input":
                ws.send(json.dumps({"type": "output", "data": value["data"].replace("\r", "\r\n")}))

        ws.on_message(message)

    context.route_web_socket("**/api/v1/access/sessions/*/ws", ssh)
    page = context.new_page()
    page.set_default_timeout(8000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda r: (
            writes.append(r.post_data)
            if r.method == "PUT" and r.url.endswith("/preferences/terminal")
            else None
        ),
    )
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def request(path, method="GET", data=None):
        response = context.request.fetch(
            BASE + "/api/v1" + path, method=method, data=data, headers={"X-Netrix-Request": "1"}
        )
        assert response.ok, (response.status, response.text())
        return response.json() if response.status != 204 else None

    def font_cells_aligned():
        page.wait_for_function("""() => {
          const row=document.querySelector('.xterm-rows');
          const span=row?.querySelector('span'); if(!span?.textContent) return false;
          const style=getComputedStyle(span), ctx=document.createElement('canvas').getContext('2d');
          ctx.font=`${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
          return Math.abs(span.getBoundingClientRect().width/span.textContent.length-ctx.measureText('W').width)<0.1;
        }""")

    prefs = request("/access/preferences")
    prefs["terminal"] = {
        "font": "ubuntu",
        "font_size": 15,
        "font_weight": 400,
        "background": "#300a24",
        "commands_width": 300,
        "commands_collapsed": False,
    }
    prefs = request("/access/preferences", "PUT", prefs)
    items = [
        {"id": "a", "name": "Conf", "command": "show version"},
        {"id": "b", "name": "running conf", "command": "show running-config"},
    ]
    request("/access/commands", "PUT", {"items": items})
    page.reload()
    page.wait_for_load_state("networkidle")
    device = request("/access/devices")["items"][0]
    page.evaluate("d=>window.dispatchEvent(new CustomEvent('netrix:ssh-open',{detail:d}))", device)
    terminal = page.locator(".ssh-dialog[open]")
    expect(terminal.locator(".xterm-rows")).to_contain_text("SW-01#")
    expect(terminal.locator(".ssh-command-list > div")).to_have_count(2)
    assert (
        terminal.locator(".xterm-rows")
        .evaluate("e=>getComputedStyle(e).fontFamily")
        .startswith('"Ubuntu Mono"')
    )
    assert (
        terminal.locator(".ssh-terminal").evaluate("e=>getComputedStyle(e).backgroundImage")
        .startswith("linear-gradient(")
    )
    assert terminal.locator(".xterm-cursor-blink").count() == 0
    font_cells_aligned()
    # Both short and long labels share one left axis; all three actions have the same height.
    positions = terminal.locator(".ssh-command-run span").evaluate_all(
        "es=>es.map(e=>e.getBoundingClientRect().left)"
    )
    assert max(positions) - min(positions) < 1, positions
    assert set(
        terminal.locator(".ssh-command-list button").evaluate_all(
            "es=>es.map(e=>e.getBoundingClientRect().height)"
        )
    ) == {44}
    terminal.get_by_role("button", name="Conf komutunu düzenle", exact=True).click()
    terminal.get_by_label("Komut adı", exact=True).fill("Configuration")
    terminal.get_by_label("Komut", exact=True).fill("show system\nshow version")
    terminal.get_by_role("button", name="Değişiklikleri kaydet", exact=True).click()
    expect(terminal.get_by_role("button", name="Configuration komutunu çalıştır")).to_be_visible()
    saved = request("/access/commands")["items"]
    assert [v["id"] for v in saved] == ["a", "b"] and saved[0]["command"] == "show system\nshow version"
    terminal.get_by_role("button", name="Configuration komutunu düzenle").click()
    terminal.get_by_label("Komut adı", exact=True).fill("UNSAVED")
    terminal.get_by_role("button", name="Vazgeç", exact=True).click()
    assert request("/access/commands")["items"] == saved
    terminal.get_by_role("button", name="Configuration komutunu çalıştır").click()
    page.wait_for_function("()=>document.querySelector('.xterm-rows').textContent.includes('show system')")
    assert any(v == {"type": "input", "data": "show system\rshow version\r"} for v in frames)
    # Editing is also allowed at the 50-command limit.
    many = saved + [{"id": str(i), "name": f"Command {i}", "command": "show version"} for i in range(48)]
    request("/access/commands", "PUT", {"items": many})
    page.evaluate("items=>window.dispatchEvent(new CustomEvent('netrix:commands',{detail:items}))", many)
    terminal.get_by_role("button", name="Configuration komutunu düzenle").click()
    expect(terminal.get_by_role("button", name="Değişiklikleri kaydet")).to_be_enabled()
    terminal.get_by_role("button", name="Vazgeç", exact=True).click()
    request("/access/commands", "PUT", {"items": saved})
    page.evaluate("items=>window.dispatchEvent(new CustomEvent('netrix:commands',{detail:items}))", saved)
    # One write on drag release; no write per pointer movement.
    separator = terminal.get_by_role("separator", name="Hazır komut panelinin genişliği")
    box = separator.bounding_box()
    old_writes = len(writes)
    page.mouse.move(box["x"] + 4, box["y"] + 70)
    page.mouse.down()
    page.mouse.move(box["x"] - 116, box["y"] + 70, steps=15)
    assert len(writes) == old_writes
    page.mouse.up()
    page.wait_for_function("()=>document.querySelector('.ssh-footer').textContent.includes('kaydedildi')")
    assert len(writes) == old_writes + 1
    assert request("/access/preferences")["terminal"]["commands_width"] == 420
    separator.focus()
    separator.press("ArrowLeft")
    expect(separator).to_have_attribute("aria-valuenow", "440")
    page.wait_for_function("()=>document.querySelector('.ssh-footer').textContent.includes('kaydedildi')")
    terminal.get_by_role("button", name="Hazır komutları gizle").click()
    expect(terminal.get_by_role("button", name="Hazır komutları göster")).to_be_visible()
    terminal.get_by_role("button", name="Hazır komutları göster").click()
    expect(terminal.get_by_role("heading", name="Hazır komutlar")).to_be_visible()
    # Appearance is applied in place: no reconnect, clear, or lost output.
    terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
    terminal.get_by_label("Yazı tipi", exact=True).select_option("plex")
    terminal.get_by_label("Yazı kalınlığı", exact=True).select_option("700")
    terminal.get_by_label("Yazı boyutu", exact=True).select_option("22")
    terminal.get_by_label("Başlangıç rengi", exact=True).fill("#ffffff")
    terminal.get_by_label("Bitiş rengi", exact=True).fill("#32456a")
    terminal.get_by_role("slider", name="Saydamlık").fill("35")
    expect(terminal.locator(".ssh-opacity-label output")).to_have_text("35%")
    expect(terminal.locator(".ssh-terminal")).to_have_css("opacity", "1")
    assert "0.65" in terminal.locator(".ssh-terminal").evaluate("e=>getComputedStyle(e).backgroundImage")
    page.wait_for_function("()=>getComputedStyle(document.querySelector('.xterm-rows')).fontSize==='22px'")
    expect(terminal.locator(".xterm-rows")).to_contain_text("NETRIX terminal fixture")
    terminal.get_by_role("button", name="Görünümü kaydet").click()
    expect(terminal.get_by_role("form", name="Terminal görünüm ayarları")).to_have_count(0)
    font_cells_aligned()
    prefs = request("/access/preferences")
    assert prefs["terminal"] == {
        "font": "plex",
        "font_size": 22,
        "font_weight": 700,
        "background": "#ffffff",
        "background_end": "#32456a",
        "background_opacity": 65,
        "commands_width": 440,
        "commands_collapsed": False,
    }
    assert connections == 1
    terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
    terminal.get_by_role("button", name="Ubuntu varsayılanı").click()
    terminal.get_by_role("button", name="Vazgeç", exact=True).click()
    page.wait_for_function("()=>getComputedStyle(document.querySelector('.xterm-rows')).fontSize==='22px'")
    assert request("/access/preferences")["terminal"] == prefs["terminal"]
    terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
    terminal.get_by_role("button", name="Ubuntu varsayılanı").click()
    terminal.get_by_role("button", name="Görünümü kaydet").click()
    expect(terminal.get_by_role("form", name="Terminal görünüm ayarları")).to_have_count(0)
    font_cells_aligned()
    # No idle cursor movement or resize flood after geometry settles.
    terminal.locator(".xterm-helper-textarea").focus()
    page.wait_for_timeout(400)
    rect = terminal.locator(".xterm-cursor").bounding_box()
    resize_count = len([v for v in frames if v["type"] == "resize"])
    page.wait_for_timeout(1000)
    assert terminal.locator(".xterm-cursor").bounding_box() == rect
    assert len([v for v in frames if v["type"] == "resize"]) == resize_count
    terminal.get_by_role("button", name="Simge durumuna küçült").click()
    page.get_by_role("button", name=f"{device['name']} SSH oturumunu aç", exact=True).click()
    expect(terminal).to_be_visible()
    assert connections == 1
    font_cells_aligned()
    terminal.get_by_role("button", name="Tam ekran", exact=True).click()
    expect(terminal).to_have_class("ssh-dialog ssh-full")
    terminal.get_by_role("button", name="Pencereyi küçült", exact=True).click()

    def capture(key):
        font_cells_aligned()
        assert terminal.locator(".ssh-footer").evaluate(
            "e=>e.getBoundingClientRect().bottom<=innerHeight+1"
        ), key
        assert terminal.evaluate("e=>e.scrollWidth<=e.clientWidth"), key
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), key
        positions = terminal.locator(".ssh-command-run span").evaluate_all(
            "es=>es.map(e=>e.getBoundingClientRect().left)"
        )
        assert max(positions) - min(positions) < 1, (key, positions)
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        violations[key] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))"
        )
        page.screenshot(path=str(OUT / f"{key}.png"))
        (OUT / "partial.json").write_text(json.dumps(violations, indent=2))

    # Minimum and maximum widths keep header tools inside the panel.
    separator.focus()
    separator.press("Home")
    expect(separator).to_have_attribute("aria-valuenow", "240")
    page.wait_for_function("()=>document.querySelector('.ssh-footer').textContent.includes('kaydedildi')")
    assert terminal.locator(".ssh-command-tools").evaluate(
        "e=>e.getBoundingClientRect().right<=e.closest('.ssh-commands').getBoundingClientRect().right"
    ), "minimum-width tools overflow"
    capture("minimum-panel-width")
    separator.press("End")
    expect(separator).to_have_attribute("aria-valuenow", "560")
    page.wait_for_function("()=>document.querySelector('.ssh-footer').textContent.includes('kaydedildi')")
    capture("maximum-panel-width")
    terminal.get_by_role("button", name="Hazır komutları daralt", exact=True).click()
    expect(separator).to_have_attribute("aria-valuenow", "500")
    page.wait_for_function("()=>document.querySelector('.ssh-footer').textContent.includes('kaydedildi')")
    terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
    terminal.get_by_label("Yazı tipi", exact=True).select_option("system")
    terminal.get_by_label("Yazı boyutu", exact=True).select_option("28")
    terminal.get_by_label("Yazı kalınlığı", exact=True).select_option("700")
    font_cells_aligned()
    terminal.get_by_role("button", name="Vazgeç", exact=True).click()
    font_cells_aligned()
    for design in ("lumelle",):
        for mode in ("dark", "light"):
            page.evaluate(
                "v=>{document.documentElement.dataset.design=v.design;document.documentElement.dataset.theme=v.mode;document.documentElement.dataset.palette='amber'}",
                {"design": design, "mode": mode},
            )
            for width in (1440, 375):
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
                page.wait_for_timeout(600)
                capture(f"{design}-{mode}-{width}-commands")
                terminal.get_by_role("button", name="Terminal görünümü", exact=True).click()
                capture(f"{design}-{mode}-{width}-appearance")
                terminal.get_by_role("button", name="Vazgeç", exact=True).click()
    page.set_viewport_size({"width": 812, "height": 375})
    page.wait_for_function("document.querySelector('.ssh-footer').getBoundingClientRect().bottom <= innerHeight + 1")
    capture("landscape-commands")
    assert connections == 1
    assert not errors, errors
    failures = {k: v for k, v in violations.items() if v}
    (OUT / "report.json").write_text(
        json.dumps(
            {
                "screens": len(violations),
                "violations": failures,
                "errors": errors,
                "connections": connections,
                "idle_cursor_stable": True,
                "resize_deduplicated": True,
            },
            indent=2,
        )
    )
    assert not failures, failures
    browser.close()
print(
    json.dumps({"screens": len(violations), "errors": errors, "violations": {}, "connections": connections})
)
