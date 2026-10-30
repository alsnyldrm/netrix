"""Automatic port selection, explicit exclusions and live draft preservation; local fixture only."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8205"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    errors, reports, sockets, saves = [], {}, [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket("**/api/v1/ws", lambda socket: sockets.append(socket))
    page.on(
        "request",
        lambda r: (
            saves.append(r.post_data_json) if r.method == "PUT" and r.url.endswith("/interfaces") else None
        ),
    )
    Path("artifacts").mkdir(exist_ok=True)

    def checkbox(name):
        return page.get_by_role("checkbox", name=name + " uygulamaya ekle", exact=True)

    def observe(state):
        result = page.evaluate(
            "async state=>{const r=await fetch('/_fixture/ports/'+state,{method:'POST',headers:{'X-Netrix-Request':'1'}});return r.status}",
            state,
        )
        assert result == 200
        sockets[-1].send(json.dumps({"type": "refresh"}))

    def check(name):
        for width, height in ((1440, 1000), (375, 812)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.locator(".interface-picker").scroll_into_view_if_needed()
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                dialog = page.get_by_role("dialog")
                assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                for card in page.locator(".port-choice").all():
                    centers = card.evaluate(
                        "e=>{const a=e.getBoundingClientRect(),b=e.querySelector('input').getBoundingClientRect();return {a:a.y+a.height/2,b:b.y+b.height/2}}"
                    )
                    assert abs(centers["a"] - centers["b"]) <= 1, centers
                offsets = page.locator(".port-choice").evaluate_all(
                    "cards=>cards.map(e=>e.querySelector('b').getBoundingClientRect().top-e.getBoundingClientRect().top)"
                )
                assert max(offsets) - min(offsets) <= 1, offsets
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
                )
                page.screenshot(path=f"artifacts/interface-auto-{name}-{width}-{theme}.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("textbox", name="Kayıtlarda ara", exact=True).fill("Fixture 00")
    page.get_by_role("button", name="Fixture 00 ayrıntıları", exact=True).click()
    expect(checkbox("port1")).to_be_checked()
    for name in ("port2", "port3", "port4"):
        expect(checkbox(name)).not_to_be_checked()
    save = page.get_by_role("button", name="Arayüz seçimini kaydet", exact=True)
    expect(save).to_be_disabled()
    check("defaults")
    checkbox("port1").uncheck()
    observe("up")
    expect(checkbox("port2")).to_be_checked()
    expect(checkbox("port1")).not_to_be_checked()
    check("live-draft")
    save.click()
    expect(page.get_by_role("status")).to_contain_text("Arayüz seçimi kaydedildi")
    assert len(saves[-1]["exclude_ids"]) == 1 and not saves[-1]["include_ids"] and "ids" not in saves[-1]
    observe("down")
    expect(page.locator(".port-choice").filter(has=checkbox("port1"))).to_contain_text("Kapalı")
    expect(checkbox("port1")).not_to_be_checked()
    observe("up")
    expect(page.locator(".port-choice").filter(has=checkbox("port1"))).to_contain_text("Açık")
    expect(checkbox("port1")).not_to_be_checked()
    expect(checkbox("port2")).to_be_checked()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Fixture 00 ayrıntıları", exact=True).click()
    expect(checkbox("port1")).not_to_be_checked()
    expect(page.locator(".port-choice").filter(has=checkbox("port1"))).to_contain_text(
        "Otomatik ekleme kapalı"
    )
    check("persisted")
    # Clearing visible closed ports is an explicit opt-out; untouched closed ports are not.
    page.get_by_role("textbox", name="Arayüzlerde ara", exact=True).fill("port4")
    page.get_by_role("button", name="Görünenleri kaldır", exact=True).click()
    save.click()
    expect(save).to_be_disabled()
    page.get_by_role("textbox", name="Arayüzlerde ara", exact=True).fill("")
    observe("all")
    expect(page.locator(".port-choice").filter(has=checkbox("port4"))).to_contain_text("Açık")
    expect(checkbox("port4")).not_to_be_checked()
    checkbox("port1").check()
    save.click()
    expect(save).to_be_disabled()
    observe("down")
    expect(checkbox("port1")).to_be_checked()
    expect(page.locator(".port-choice").filter(has=checkbox("port1"))).to_contain_text("Kapalı")
    check("manual-reinclude")
    assert not any(reports.values()), reports
    assert not errors, errors
    print(
        json.dumps(
            {"automatic_ports": "PASS", "delta_saves": len(saves), "axe": reports, "console_errors": errors}
        )
    )
    browser.close()
