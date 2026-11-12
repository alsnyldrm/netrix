"""Account font selection with real local font files and isolated HTTP; no device traffic."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8241")
OUT = Path("artifacts/application-fonts")
OUT.mkdir(parents=True, exist_ok=True)
errors, failures, requests, violations = [], [], [], {}
checks = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda req: requests.append(req.url))
    # The anonymous login screen intentionally receives 401 from /auth/me.
    page.on(
        "response",
        lambda res: (
            failures.append((res.url, res.status))
            if res.status >= 400 and not (res.status == 401 and urlparse(res.url).path == "/api/v1/auth/me")
            else None
        ),
    )
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def open_fonts():
        page.get_by_role("button", name="Hesap menüsü", exact=True).click()
        page.get_by_role("button", name="Profil", exact=True).click()
        dialog = page.get_by_role("dialog", name="Profil", exact=True)
        dialog.get_by_role("button", name="Yazı tipi", exact=True).click()
        return dialog

    profile = open_fonts()
    picker = profile.get_by_role("combobox", name="Yazı tipi", exact=True)
    expect(picker).to_be_visible()
    options = picker.locator("option").evaluate_all(
        "es=>es.filter(e=>e.value!=='theme').map(e=>({id:e.value,name:e.textContent}))"
    )
    assert len(options) >= 15 and len({option["id"] for option in options}) == len(options), options
    initial = context.request.get(BASE + "/api/v1/access/preferences").json()
    assert initial["ui_font"] == "theme"

    def select_font(id):
        picker.select_option(id)
        expect(profile.get_by_role("status")).to_contain_text("Tercihleriniz kaydedildi")
        page.wait_for_function("id=>document.documentElement.dataset.uiFont===id", arg=id)
        if id != "theme":
            loaded = page.evaluate("""async()=> {
              const family=getComputedStyle(document.documentElement).fontFamily.split(',')[0];
              const text='Çç Ğğ Iı İi Öö Şş Üü 0123456789';
              const faces=await Promise.all([400,500,600,700].map(w=>document.fonts.load(`${w} 15px ${family}`,text)));
              return faces.every(items=>items.length>0 && items.every(face=>face.status==='loaded'));
            }""")
            assert loaded, id

    def geometry(key):
        global checks
        picker.scroll_into_view_if_needed()
        state = page.evaluate("""() => {
          const d=document.querySelector('dialog[open]'),c=d.querySelector('.profile-content'),s=d.querySelector('select[name="ui-font"]'),p=d.querySelector('.application-font-preview');
          const cr=c.getBoundingClientRect(),sr=s.getBoundingClientRect(),pr=p.getBoundingClientRect();
          return {pageOverflow:document.body.scrollWidth>innerWidth,dialogOverflow:d.scrollWidth>d.clientWidth,
            aligned:Math.abs(sr.left-pr.left)<1 && Math.abs(sr.right-pr.right)<1,
            inside:sr.left>=cr.left && sr.right<=cr.right,
            font:getComputedStyle(s).fontFamily, previewFont:getComputedStyle(p).fontFamily};
        }""")
        assert not state["pageOverflow"] and not state["dialogOverflow"], (key, state)
        assert state["aligned"] and state["inside"] and state["font"] == state["previewFont"], (key, state)
        checks += 1

    for option in options:
        select_font(option["id"])
        assert context.request.get(BASE + "/api/v1/access/preferences").json() == {
            **initial,
            "ui_font": option["id"],
        }
        for width in (1440, 375):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
            for design in ("lumelle",):
                page.evaluate("v=>document.documentElement.dataset.design=v", design)
                for mode in ("light", "dark"):
                    page.evaluate("m=>document.documentElement.dataset.theme=m", mode)
                    geometry(f"{option['id']}-{design}-{width}-{mode}")
        if option["id"] in ("inter", "lexend", "plus-jakarta-sans"):
            page.screenshot(path=str(OUT / (option["id"] + "-mobile.png")))
        page.set_viewport_size({"width": 1440, "height": 1000})
    # Keep the user's selected font across page reloads and theme/palette saves.
    select_font("inter")
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(page.locator("html")).to_have_attribute("data-ui-font", "inter")
    profile = open_fonts()
    picker = profile.get_by_role("combobox", name="Yazı tipi", exact=True)
    expect(picker).to_have_value("inter")
    profile.get_by_role("button", name="Tema", exact=True).click()
    profile.get_by_role("button", name="Koyu", exact=True).click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.locator("html")).to_have_attribute("data-ui-font", "inter")
    profile.get_by_role("button", name="Renk paleti", exact=True).click()
    profile.locator(".palette-option").filter(has_text="Ametist").click()
    expect(profile.get_by_role("status")).to_contain_text("Tercihleriniz kaydedildi")
    expect(page.locator("html")).to_have_attribute("data-ui-font", "inter")
    profile.get_by_role("button", name="Yazı tipi", exact=True).click()
    for design in ("lumelle",):
        for mode in ("light", "dark"):
            page.evaluate(
                "v=>Object.assign(document.documentElement.dataset,v)", {"design": design, "theme": mode}
            )
            for width, height in ((1440, 1000), (375, 812), (812, 375)):
                page.set_viewport_size({"width": width, "height": height})
                geometry(f"{design}-{mode}-{width}")
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                key = f"{design}-{mode}-{width}"
                violations[key] = page.evaluate(
                    "async()=>(await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                page.screenshot(path=str(OUT / (key + ".png")))
    page.set_viewport_size({"width": 1440, "height": 1000})
    select_font("theme")
    assert page.locator("html").evaluate("e=>e.style.getPropertyValue('--font-sans')") == ""
    select_font("inter")
    # Another account has its own default, including when returning to login.
    profile.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    context.request.post(BASE + "/api/v1/auth/logout", headers={"X-Netrix-Request": "1"})
    page.reload()
    page.get_by_label("E-posta", exact=True).fill("viewer@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("html")).to_have_attribute("data-ui-font", "theme")
    font_requests = [url for url in requests if urlparse(url).path.endswith((".woff2", ".woff", ".ttf"))]
    assert font_requests and all(urlparse(url).netloc == urlparse(BASE).netloc for url in font_requests)
    assert not errors and not failures, (errors, failures)
    violations = {key: value for key, value in violations.items() if value}
    assert not violations, violations
    report = {
        "fonts": len(options),
        "geometry_checks": checks,
        "accessibility_screens": 30,
        "violations": violations,
        "errors": errors,
        "font_requests_local": True,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    browser.close()
