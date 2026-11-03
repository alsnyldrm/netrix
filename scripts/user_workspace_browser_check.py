"""Desktop/mobile workspace controls with real HTTP API and explicit terminal mocks."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
Path("artifacts").mkdir(exist_ok=True)
reports = {}
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)
    sent = []

    def terminal(ws):
        ws.send(json.dumps({"type": "status", "status": "connected"}))
        ws.send(json.dumps({"type": "output", "data": "NETRIX fixture terminal\r\nSW-01# "}))

        def message(raw):
            value = json.loads(raw)
            if value["type"] == "input":
                sent.append(value["data"])
                ws.send(
                    json.dumps({"type": "output", "data": value["data"] + "\r\nfixture output\r\nSW-01# "})
                )

        ws.on_message(message)

    context.route_web_socket("**/api/v1/access/sessions/*/ws", terminal)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".ssh-launch-cell button")).to_have_count(25)

    def check(name, axe=True):
        # Chromium needs a settled paint for inherited colors in nested native modals.
        page.wait_for_timeout(400)
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        if axe:
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[name] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
        Path("artifacts/user-workspace-partial.json").write_text(json.dumps(reports, indent=2))
        page.screenshot(path=f"artifacts/user-workspace-{name}.png")

    for width, theme in ((1440, "light"), (1440, "dark"), (375, "light"), (375, "dark")):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        if width < 1024:
            page.get_by_role("button", name="Menüyü aç", exact=True).click()
        page.get_by_role("button", name="Profil", exact=True).click()
        dialog = page.get_by_role("dialog", name="Profil", exact=True)
        for tab in ("Hesabım", "Renk paleti", "Tarih, saat ve bölge", "Özellikler"):
            dialog.get_by_role("button", name=tab, exact=True).click()
            check(f"profile-{tab}-{width}-{theme}")
            if tab == "Renk paleti":
                for name in ("Teknik kobalt", "Atlantik", "Ametist", "Bakır", "Orman", "Grafit"):
                    dialog.get_by_role("button", name=name, exact=True).click()
                    expect(dialog.get_by_role("button", name=name, exact=True)).to_have_attribute(
                        "aria-pressed", "true"
                    )
                    check(f"palette-{name}-{width}-{theme}")
                rects = dialog.locator(".palette-option").evaluate_all(
                    "els=>els.map(e=>{let r=e.getBoundingClientRect(),s=e.querySelector('.palette-swatch').getBoundingClientRect();return {x:r.x,y:r.y,h:r.height,sx:s.x-r.x,sy:s.y-r.y}})"
                )
                assert max(r["sx"] for r in rects) - min(r["sx"] for r in rects) < 1, rects
                assert max(r["h"] for r in rects) - min(r["h"] for r in rects) < 1, rects
        dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
        page.get_by_role("button", name="SW-01 SSH bağlantısı", exact=True).click()
        terminal_dialog = page.get_by_role("dialog", name="SW-01 SSH bağlantısı", exact=True)
        expect(terminal_dialog.locator(".ssh-state")).to_have_text("Bağlı")
        expect(terminal_dialog.locator(".xterm")).to_be_visible()
        check(f"terminal-{width}-{theme}")
        buttons = terminal_dialog.locator(".ssh-window-actions button").evaluate_all(
            "els=>els.map(e=>{let r=e.getBoundingClientRect();return [r.y,r.height]})"
        )
        assert len(set(round(y, 1) for y, h in buttons)) == 1, buttons
        assert len(set(round(h, 1) for y, h in buttons)) == 1, buttons
        terminal_dialog.get_by_role("button", name="Tam ekran", exact=True).click()
        expect(terminal_dialog).to_have_class("ssh-dialog ssh-full")
        terminal_dialog.get_by_role("button", name="Pencereyi küçült", exact=True).click()
        terminal_dialog.get_by_role("button", name="Simge durumuna küçült", exact=True).click()
        expect(page.locator(".ssh-dock")).to_be_visible()
        page.get_by_role("button", name="SW-01 SSH oturumunu aç", exact=True).click()
        terminal_dialog.get_by_role("button", name="SSH bağlantısını kapat", exact=True).click()
        expect(terminal_dialog).not_to_be_visible()

    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="Profil", exact=True).click()
    profile_dialog = page.get_by_role("dialog", name="Profil", exact=True)
    assert page.locator(".sidebar").get_by_text("Cihaz yetkisi", exact=True).count() == 0
    profile_dialog.get_by_role("button", name="SSH Bağlantısı", exact=True).click()
    expect(page.get_by_role("heading", name="Kişisel SSH bağlantısı")).to_be_visible()
    expect(profile_dialog).to_contain_text("Ekip & yetkiler")
    assert profile_dialog.get_by_text("Cihaz grubu yetkisi gereklidir.", exact=False).count() == 0
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"ssh-settings-{width}-{theme}")
    page.set_viewport_size({"width": 1440, "height": 1000})
    profile_dialog.get_by_label("Kullanıcı adı", exact=True).fill("fixture-updated")
    profile_dialog.get_by_role("button", name="Bağlantıyı kaydet", exact=True).click()
    expect(page.get_by_text("Kişisel SSH bağlantınız kaydedildi.")).to_be_visible()
    profile_dialog.get_by_role("button", name="Cihaz grupları", exact=True).click()
    profile_dialog.get_by_role("button", name="Grup oluştur", exact=True).click()
    dialog = page.get_by_role("dialog", name="Yeni cihaz grubu", exact=True)
    dialog.get_by_label("Grup adı", exact=True).fill("Access fixture group")
    expect(dialog.locator(".group-device-list > label")).to_have_count(100)
    dialog.get_by_label("Bu sayfayı seç", exact=True).check()
    expect(dialog.get_by_role("heading", name="Cihazlar")).to_contain_text("100 seçili")
    dialog.get_by_role("button", name="Sonraki", exact=True).click()
    expect(dialog.get_by_label("Bu sayfayı seç", exact=True)).not_to_be_checked()
    dialog.locator(".group-device-list input").first.check()
    expect(dialog.get_by_role("heading", name="Cihazlar")).to_contain_text("101 seçili")
    dialog.get_by_role("button", name="Seçimi temizle", exact=True).click()
    dialog.get_by_role("button", name="Filtreler", exact=True).click()
    filters = page.get_by_role("dialog", name="Filtreler", exact=True)
    available = filters.get_by_label("Koşul 1 alanı", exact=True).locator("option").all_text_contents()
    assert all(label in available for label in ["Model", "Üretici", "Versiyon"]), available
    filters.get_by_label("Koşul 1 alanı", exact=True).select_option("model")
    filters.get_by_label("Koşul 1 değeri", exact=True).fill("CX6200")
    expect(filters.locator("datalist option[value=CX6200]")).to_have_count(1)
    filters.get_by_role("button", name="Koşul ekle", exact=True).click()
    filters.get_by_label("Koşul 2 alanı", exact=True).select_option("software_version")
    filters.get_by_label("Koşul 2 değeri", exact=True).fill("10.13")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"group-filters-{width}-{theme}")
    filters.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    expect(dialog.get_by_role("button", name="Tüm eşleşenleri seç (150)", exact=True)).to_be_enabled()
    dialog.get_by_role("button", name="Tüm eşleşenleri seç (150)", exact=True).click()
    expect(dialog.get_by_role("heading", name="Cihazlar")).to_contain_text("150 seçili")
    dialog.get_by_label("Tüm alanlarda ara", exact=True).fill("SW-01")
    expect(dialog.locator(".group-device-list > label")).to_have_count(1)
    expect(dialog.locator(".group-device-list input")).to_be_checked()
    expect(dialog.get_by_role("heading", name="Cihazlar")).to_contain_text("150 seçili")
    assert dialog.get_by_text("SSH Bağlantısı yetkisi", exact=True).count() == 0
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"group-form-{width}-{theme}")
        boxes = dialog.locator(".form-grid input").evaluate_all(
            "es=>es.map(e=>e.getBoundingClientRect().height)"
        )
        assert max(boxes) - min(boxes) < 1, boxes
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(profile_dialog.locator(".access-group-cards")).to_contain_text("150 cihaz")
    profile_dialog.get_by_role("button", name="Access fixture group düzenle", exact=True).click()
    dialog = page.get_by_role("dialog", name="Cihaz grubunu düzenle", exact=True)
    expect(dialog.get_by_role("heading", name="Cihazlar")).to_contain_text("150 seçili")
    dialog.get_by_label("Grup adı", exact=True).fill("Updated group")
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(profile_dialog.locator(".access-group-cards")).to_contain_text("Updated group")
    profile_dialog.get_by_role("button", name="Updated group sil", exact=True).click()
    page.get_by_role("button", name="Grubu sil", exact=True).click()
    expect(profile_dialog.locator(".access-group-cards article")).to_have_count(0)
    profile_dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(BASE + "/#users")
    page.get_by_role("button", name="Viewer Tester rollerini düzenle", exact=True).click()
    roles = page.get_by_role("dialog", name="Kullanıcı rollerini düzenle", exact=True)
    roles.get_by_label("SSH bağlantısı", exact=True).check()
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"user-roles-{width}-{theme}")
    roles.get_by_role("button", name="Rolleri kaydet", exact=True).click()
    expect(roles).not_to_be_visible()
    result = page.request.get(BASE + "/api/v1/users").json()
    viewer = next(u for u in result["items"] if u["email"] == "viewer@example.test")
    assert viewer["ssh_access"] is True and viewer["role"] == "viewer"
    page.set_viewport_size({"width": 1440, "height": 1000})

    page.goto(BASE + "/#devices")
    page.get_by_label("SW-01 seç", exact=True).check()
    page.get_by_label("SW-02 seç", exact=True).check()
    page.get_by_role("button", name="Toplu komut gönder", exact=True).click()
    dialog = page.get_by_role("dialog", name="Toplu komut gönder", exact=True)
    dialog.get_by_label("Gönderilecek komut", exact=True).fill("show version")
    dialog.get_by_role("button", name="Komutu gönder", exact=True).click()
    expect(dialog.locator(".batch-summary")).to_contain_text("1 başarılı · 1 başarısız")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for theme in ("light", "dark"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"batch-results-{width}-{theme}")
    dialog.get_by_role("button").filter(has_text="SW-01").click()
    expect(dialog.locator("pre")).to_contain_text("NETRIX fixture SSH output")
    dialog.get_by_role("button").filter(has_text="SW-02").click()
    expect(dialog.locator("pre")).to_contain_text("Fixture: authentication failed")
    dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="SW-01 SSH bağlantısı", exact=True).click()
    dialog = page.get_by_role("dialog", name="SW-01 SSH bağlantısı", exact=True)
    dialog.get_by_role("button", name="Hazır komut kaydet", exact=True).click()
    dialog.get_by_label("Komut adı", exact=True).fill("Version fixture")
    dialog.get_by_label("Komut", exact=True).fill("show version")
    dialog.get_by_role("button", name="Komutu kaydet", exact=True).click()
    dialog.get_by_role("button", name="Version fixture", exact=True).click()
    page.wait_for_timeout(100)
    assert "show version\r" in sent, sent
    with page.expect_popup() as popup:
        dialog.get_by_role("button", name="Yeni sekmede aç", exact=True).click()
    other = popup.value
    expect(other.locator(".ssh-dialog")).to_be_visible()
    assert other.url.startswith(BASE + "/terminal/")
    assert other.evaluate("window.opener===null")
    expect(page.locator(".ssh-dialog[open]")).to_have_count(0)
    other.get_by_role("button", name="SSH bağlantısını kapat", exact=True).click()
    other.close()
    for n in range(1, 16):
        page.get_by_role("button", name=f"SW-{n:02} SSH bağlantısı", exact=True).click()
        dialog = page.get_by_role("dialog", name=f"SW-{n:02} SSH bağlantısı", exact=True)
        dialog.get_by_role("button", name="Simge durumuna küçült", exact=True).click()
    expect(page.locator(".ssh-dock > div")).to_have_count(15)
    page.get_by_role("button", name="SW-16 SSH bağlantısı", exact=True).click()
    dialog = page.get_by_role("dialog", name="SW-16 SSH bağlantısı", exact=True)
    dialog.get_by_role("button", name="Simge durumuna küçült", exact=True).click()
    expect(page.get_by_role("dialog", name="SSH bağlantısı", exact=True)).to_contain_text(
        "En fazla 15 oturum"
    )
    page.get_by_role("button", name="Tamam", exact=True).click()
    expect(page.locator(".ssh-dock > div")).to_have_count(15)
    dialog.get_by_role("button", name="SSH bağlantısını kapat", exact=True).click()
    check("dock-limit-1440-light", axe=False)
    page.get_by_role("button", name="Profil", exact=True).click()
    profile_dialog = page.get_by_role("dialog", name="Profil", exact=True)
    profile_dialog.get_by_role("button", name="Özellikler", exact=True).click()
    compact = profile_dialog.locator("label").filter(has_text="Sıkı tablo düzeni").locator("input")
    compact.check()
    expect(page.locator("html")).to_have_attribute("data-compact", "true")
    compact.uncheck()
    expect(page.locator("html")).to_have_attribute("data-compact", "false")
    motion = profile_dialog.locator("label").filter(has_text="Azaltılmış hareket").locator("input")
    motion.check()
    expect(page.locator("html")).to_have_attribute("data-reduce-motion", "true")
    profile_dialog.get_by_role("button", name="Tarih, saat ve bölge", exact=True).click()
    profile_dialog.get_by_label("Saat dilimi", exact=True).fill("UTC")
    profile_dialog.get_by_label("Bölgesel biçim").select_option("en-US")
    profile_dialog.get_by_label("Saat biçimi").select_option("true")
    profile_dialog.get_by_role("button", name="Tercihleri kaydet", exact=True).click()
    expect(profile_dialog.get_by_role("status")).to_contain_text("Tercihleriniz kaydedildi.")
    preference = context.request.get(BASE + "/api/v1/access/preferences").json()
    assert (
        preference["timezone"] == "UTC" and preference["locale"] == "en-US" and preference["hour12"] is True
    ), preference
    check("functional-preferences-1440-light")
    profile_dialog.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    violations = {key: value for key, value in reports.items() if value}
    Path("artifacts/user-workspace-browser.json").write_text(
        json.dumps({"violations": violations, "errors": errors, "checks": len(reports)}, indent=2)
    )
    assert not violations, violations
    assert not errors, errors
    browser.close()
print(json.dumps({"checks": len(reports), "violations": 0, "errors": 0}))
