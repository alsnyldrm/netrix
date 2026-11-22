# ruff: noqa: E402
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "backend"))
from netrix.core import now
from netrix.identity.mfa import totp
from playwright.sync_api import sync_playwright

OUT = Path("artifacts/local-mfa")
OUT.mkdir(exist_ok=True, parents=True)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8298")
    page.wait_for_load_state("networkidle")
    page.get_by_label("E-posta", exact=True).fill("alisan.yildirim@fbu.edu.tr")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Giriş Yap", exact=True).click()
    page.get_by_role("heading", name="Authenticator Kurulumu").wait_for()
    secret = page.locator(".mfa-setup code").inner_text()
    for mode in ("dark", "light"):
        for width, height in ((1440, 1000), (375, 900), (812, 375)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("(mode)=>document.documentElement.dataset.theme=mode", mode)
            page.wait_for_timeout(350)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            qr = page.locator(".mfa-qr-frame img").bounding_box()
            frame = page.locator(".mfa-qr-frame").bounding_box()
            assert abs(qr["width"] - qr["height"]) < 1
            assert (
                qr["x"] >= frame["x"] - 1
                and qr["y"] >= frame["y"] - 1
                and qr["y"] + qr["height"] <= frame["y"] + frame["height"] + 1
            )
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            print(mode, width, violations, flush=True)
            page.screenshot(path=str(OUT / f"enrollment-{mode}-{width}.png"), full_page=True)
            assert not violations
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_label("6 Haneli Doğrulama Kodu").fill("111111")
    page.get_by_role("button", name="Doğrula ve Giriş Yap").click()
    page.get_by_role("alert").wait_for()
    page.screenshot(path=str(OUT / "invalid-code.png"), full_page=True)
    page.get_by_label("6 Haneli Doğrulama Kodu").fill(totp(secret, int(now().timestamp()) // 30))
    page.get_by_role("button", name="Doğrula ve Giriş Yap").click()
    page.wait_for_timeout(1000)
    assert page.locator(".auth-card").count() == 0
    page.goto("http://127.0.0.1:8298/#users")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Browser Owner rollerini düzenle").click()
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000})
        page.get_by_text("Authenticator etkin. Yerel girişlerde kod zorunlu.").wait_for()
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / f"user-mfa-{width}.png"), full_page=True)
    page.get_by_role("button", name="Vazgeç", exact=True).click()
    page.context.request.post("http://127.0.0.1:8298/api/v1/auth/logout", headers={"X-Netrix-Request": "1"})
    page.goto("http://127.0.0.1:8298")
    page.get_by_label("E-posta", exact=True).fill("alisan.yildirim@fbu.edu.tr")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Giriş Yap", exact=True).click()
    page.get_by_role("heading", name="İki Adımlı Doğrulama").wait_for()
    assert page.locator(".mfa-setup").count() == 0
    page.screenshot(path=str(OUT / "verification.png"), full_page=True)
    page.get_by_role("button", name="← Giriş ekranına dön").click()
    page.route(
        "**/api/v1/auth/status",
        lambda route: route.fulfill(json={"setup_required": False, "saml_enabled": True}),
    )
    page.reload()
    page.wait_for_load_state("networkidle")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000})
        page.get_by_role("link", name="Microsoft ile Giriş Yap").wait_for()
        assert (
            page.get_by_role("link", name="Microsoft ile Giriş Yap").get_attribute("href")
            == "/api/v1/auth/saml/login"
        )
        page.screenshot(path=str(OUT / f"microsoft-{width}.png"), full_page=True)
    page.get_by_role("button", name="Yerel Giriş", exact=True).click()
    page.get_by_label("E-posta", exact=True).wait_for()
    print("Browser checks complete", errors)
    assert not errors
    b.close()
