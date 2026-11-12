"""Password relocation and real auth flow on disposable local fixtures only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8258")
assert BASE.startswith("http://127.0.0.1:")
EMAIL = "browser@example.test"
OLD = "browser-fixture-password"
NEW = "profile-fixture-password-new"

with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page = context.new_page()
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))

    def login(password):
        page.get_by_label("E-posta", exact=True).fill(EMAIL)
        page.get_by_label("Parola", exact=True).fill(password)
        page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
        page.wait_for_load_state("networkidle")

    def check(name):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                if page.get_by_role("dialog").count():
                    assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
                    fields = page.locator(".profile-password input").evaluate_all(
                        "els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,w:r.width,h:r.height};})"
                    )
                    assert len(fields) == 2 and all(
                        abs(fields[0][k] - fields[1][k]) < 1 for k in ("x", "w", "h")
                    ), fields
                    page.get_by_role(
                        "button", name="Parolayı güncelle", exact=True
                    ).scroll_into_view_if_needed()
                    page.get_by_label("Mevcut parola", exact=True).scroll_into_view_if_needed()
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                reports[f"{name}-{width}-{theme}"] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                page.screenshot(path=f"/tmp/netrix-profile-password-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(BASE + "/#settings")
    login(OLD)
    expect(page.get_by_role("heading", name="Platform durumu", exact=True)).to_be_visible()
    expect(page.get_by_label("Mevcut parola", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Parolayı güncelle", exact=True)).to_have_count(0)
    check("system")
    page.get_by_role("button", name="Hesap menüsü", exact=True).click()
    page.get_by_role("button", name="Profil", exact=True).click()
    expect(page.get_by_role("button", name="Hesabım", exact=True)).to_have_attribute("aria-current", "page")
    check("account")
    current = page.get_by_label("Mevcut parola", exact=True)
    new = page.get_by_label("Yeni parola", exact=True)
    expect(current).to_have_attribute("autocomplete", "current-password")
    expect(new).to_have_attribute("autocomplete", "new-password")
    current.fill("wrong-fixture-password")
    new.fill(NEW)
    page.get_by_role("button", name="Parolayı güncelle", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Mevcut parola hatalı")
    expect(new).to_have_value(NEW)
    page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.get_by_role("button", name="Komut paletini aç (Ctrl K)", exact=True).click()
    page.get_by_role("textbox", name="Menü, ayar, cihaz veya VLAN ara").fill("parolamı")
    page.get_by_role(
        "button", name="Parolamı değiştir Profil · Hesabım · Parola ve şifre ayarları", exact=True
    ).click()
    expect(page.get_by_role("dialog", name="Profil", exact=True)).to_be_visible()
    expect(current).to_have_value("")
    expect(new).to_have_value("")
    second = browser.new_context(base_url=BASE)
    assert (
        second.request.post(
            "/api/v1/auth/login", headers={"Origin": BASE, "X-Netrix-Request": "1"}, data={"email": EMAIL, "password": OLD}
        ).status
        == 200
    )
    assert second.request.get("/api/v1/auth/me").status == 200
    current.fill(OLD)
    new.fill(NEW)
    page.get_by_role("button", name="Parolayı güncelle", exact=True).click()
    expect(page.get_by_role("button", name="Çalışma alanına gir", exact=True)).to_be_visible()
    assert second.request.get("/api/v1/auth/me").status == 401
    login(NEW)
    expect(page.get_by_role("button", name="Hesap menüsü", exact=True)).to_be_visible()
    page.get_by_role("button", name="Hesap menüsü", exact=True).click()
    page.get_by_role("button", name="Profil", exact=True).click()
    expect(current).to_have_value("")
    current.fill(NEW)
    new.fill(OLD)
    page.get_by_role("button", name="Parolayı güncelle", exact=True).click()
    expect(page.get_by_role("button", name="Çalışma alanına gir", exact=True)).to_be_visible()
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        json.dumps(
            {
                "relocated": "PASS",
                "search": "PASS",
                "wrong_password": "PASS",
                "password_change_and_all_sessions_revoked": "PASS",
                "new_password_login": "PASS",
                "alignment_and_axe": reports,
            }
        )
    )
    second.close()
    browser.close()
