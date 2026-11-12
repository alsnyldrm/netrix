"""Real upload/preset flows against a disposable local fixture, never production."""

import json
import os
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8259")
assert BASE.startswith("http://127.0.0.1:")
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page = context.new_page()
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors, reports = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#settings")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="Hesap menüsü", exact=True).click()
    page.get_by_role("button", name="Profil", exact=True).click()
    expect(page.get_by_role("group", name="Anime avatarları").get_by_role("button")).to_have_count(10)
    page.get_by_role("button", name="Naruto Uzumaki", exact=True).click()
    expect(page.get_by_role("button", name="Naruto Uzumaki", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator(".topbar-profile .avatar img")).to_have_attribute("src", "/avatars/naruto.png")
    page.reload()
    expect(page.locator(".topbar-profile .avatar img")).to_have_attribute("src", "/avatars/naruto.png")
    page.get_by_role("button", name="Hesap menüsü", exact=True).click()
    page.get_by_role("button", name="Profil", exact=True).click()
    expect(page.get_by_role("button", name="Naruto Uzumaki", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        for theme in ("light", "dark"):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            page.locator("#profile-avatar-title").scroll_into_view_if_needed()
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
            options = page.locator(".profile-avatar-option").evaluate_all(
                "els=>els.map(e=>{const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}})"
            )
            assert len(options) == 10
            assert max(o["w"] for o in options) - min(o["w"] for o in options) < 1
            assert max(o["h"] for o in options) - min(o["h"] for o in options) < 1
            for option in page.locator(".profile-avatar-option").all():
                option.scroll_into_view_if_needed()
            page.wait_for_function(
                "Array.from(document.querySelectorAll('.profile-avatar-option img')).every(i=>i.complete && i.naturalWidth>0)"
            )
            page.locator("#profile-avatar-title").scroll_into_view_if_needed()
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[f"{width}-{theme}"] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            page.screenshot(path=f"/tmp/netrix-profile-avatar-{width}-{theme}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    upload = page.get_by_label("Profil fotoğrafı dosyası", exact=True)
    upload.set_input_files({"name": "bad.png", "mimeType": "image/png", "buffer": b"invalid"})
    expect(page.get_by_role("alert")).to_contain_text("Geçerli, hareketsiz")
    expect(page.get_by_role("button", name="Naruto Uzumaki", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    output = BytesIO()
    Image.new("RGB", (320, 180), "purple").save(output, format="PNG")
    upload.set_input_files({"name": "portrait.png", "mimeType": "image/png", "buffer": output.getvalue()})
    expect(page.locator(".profile-avatar-notice")).to_have_text("Profil fotoğrafınız kaydedildi.")
    photo_url = page.locator(".profile-avatar-preview img").get_attribute("src")
    assert photo_url.startswith("/api/v1/access/avatar/image?v=")
    expect(page.locator(".topbar-profile .avatar img")).to_have_attribute("src", photo_url)
    assert page.locator(".profile-avatar-preview img").evaluate("i=>i.complete && i.naturalWidth===256")
    page.reload()
    expect(page.locator(".topbar-profile .avatar img")).to_have_attribute("src", photo_url)
    page.get_by_role("button", name="Hesap menüsü", exact=True).click()
    page.get_by_role("button", name="Profil", exact=True).click()
    page.get_by_role("button", name="Kaldır", exact=True).click()
    expect(page.locator(".profile-avatar-notice")).to_have_text("Profil görseliniz kaldırıldı.")
    expect(page.locator(".topbar-profile .avatar img")).to_have_count(0)
    page.get_by_role("button", name="Levi Ackerman", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="Levi Ackerman", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    assert not errors, errors
    print(
        json.dumps(
            {"flows": "preset, reload, upload, invalid upload, reset, keyboard", "axe": reports},
            ensure_ascii=False,
        )
    )
    assert all(not v for v in reports.values()), reports
    browser.close()
