"""Real HTTP profile persistence and session policy UI; SSH sockets stay mocked."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
OUT = Path("artifacts/ssh-idle")
OUT.mkdir(parents=True, exist_ok=True)
errors, reports, writes = [], {}, []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)

    def ssh(ws):
        ws.send(json.dumps({"type": "status", "status": "connected"}))
        ws.send(json.dumps({"type": "output", "data": "SW-01# "}))

    context.route_web_socket("**/api/v1/access/sessions/*/ws", ssh)
    context.on("request", lambda r: writes.append((r.method, r.url)))
    page = context.new_page()
    page.set_default_timeout(8000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Hesap menüsü", exact=True).click()
    page.get_by_role("button", name="Profil", exact=True).click()
    profile = page.get_by_role("dialog", name="Profil", exact=True)
    profile.get_by_role("button", name="SSH Bağlantısı", exact=True).click()
    edit = profile.locator(".ssh-profile-cards article").first.get_by_role("button", name="düzenle")
    edit.click()
    form = page.get_by_role("dialog", name="SSH bağlantısını düzenle", exact=True)
    idle = form.get_by_role("spinbutton", name="Hareketsizlik süresi", exact=False)
    expect(idle).to_have_value("15")
    idle.fill("0")
    assert not idle.evaluate("e=>e.checkValidity()")
    idle.fill("241")
    assert not idle.evaluate("e=>e.checkValidity()")
    idle.fill("7")
    for design in ("atlas", "orbit", "terminal", "panorama", "focus"):
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            for mode in ("light", "dark"):
                page.evaluate(
                    "([d,m])=>{document.documentElement.dataset.design=d;document.documentElement.dataset.theme=m;}",
                    [design, mode],
                )
                idle.scroll_into_view_if_needed()
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                first = form.get_by_label("Kullanıcı adı", exact=True).bounding_box()
                secret = form.get_by_label("Şifre", exact=True).bounding_box()
                timer = idle.bounding_box()
                initial = form.get_by_label("Bağlantıda ilk çalıştırılacak komut", exact=False).bounding_box()
                assert abs(first["x"] - secret["x"]) < 1
                assert abs(timer["x"] - initial["x"]) < 1
                assert abs(timer["width"] - initial["width"]) < 1
                assert 0 <= timer["x"] < timer["x"] + timer["width"] <= width
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                name = f"{design}-{width}-{mode}"
                reports[name] = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))"
                )
                assert not reports[name], (name, reports[name])
                if design == "atlas":
                    page.screenshot(path=str(OUT / f"profile-{width}-{mode}.png"))
    expect(idle).to_have_value("7")
    with page.expect_response(
        lambda r: r.request.method == "PUT" and "/access/ssh-profiles/" in r.url
    ) as saved:
        form.get_by_role("button", name="Bağlantıyı kaydet", exact=True).click()
    assert saved.value.ok and saved.value.json()["idle_timeout_minutes"] == 7
    expect(form).not_to_be_visible()
    edit.click()
    expect(idle).to_have_value("7")
    expect(form.get_by_label("Şifre", exact=True)).to_have_value("")
    form.get_by_role("button", name="Vazgeç", exact=True).click()
    profile.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.evaluate(
        "()=>{document.documentElement.dataset.design='atlas';document.documentElement.dataset.theme='dark';}"
    )
    page.get_by_role("button", name="SW-01 SSH bağlantısı", exact=True).click()
    terminal = page.get_by_role("dialog", name="SW-01 SSH bağlantısı", exact=True)
    expect(terminal.locator(".ssh-footer")).to_contain_text("7 dk hareketsizlikte kapanır")
    terminal.get_by_role("button", name="Simge durumuna küçült", exact=True).click()
    assert not any(method == "DELETE" and "/access/sessions/" in url for method, url in writes)
    page.get_by_role("button", name="SW-01 SSH oturumunu aç", exact=True).click()
    with context.expect_page() as transferred:
        terminal.get_by_role("button", name="Yeni sekmede aç", exact=True).click()
    tab = transferred.value
    tab.wait_for_load_state("networkidle")
    standalone = tab.get_by_role("dialog", name="SW-01 SSH bağlantısı", exact=True)
    expect(standalone.locator(".ssh-footer")).to_contain_text("7 dk hareketsizlikte kapanır")
    assert not any(method == "DELETE" and "/access/sessions/" in url for method, url in writes)
    standalone.get_by_role("button", name="SSH bağlantısını kapat", exact=True).click()
    expect(tab.get_by_text("SSH oturumu kapatıldı. Bu sekmeyi kapatabilirsiniz.", exact=True)).to_be_visible()
    assert sum(method == "POST" and url.endswith("/access/sessions") for method, url in writes) == 1
    assert sum(method == "DELETE" and "/access/sessions/" in url for method, url in writes) == 1
    assert not errors, errors
    (OUT / "checks.json").write_text(json.dumps({"accessibility": reports, "errors": errors}, indent=2))
    print(
        "20 desktop/mobile theme checks: aligned fields, zero accessibility violations; idle setting persisted, footer correct after tab transfer, minimize preserved session, X cancelled once."
    )
    browser.close()
