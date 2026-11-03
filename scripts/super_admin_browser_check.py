"""Real isolated HTTP users, role assignments and UI visibility. No real SSH traffic."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
OUT = Path("artifacts/super-admin")
OUT.mkdir(parents=True, exist_ok=True)
reports, errors = {}, []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    def login(email):
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
        )
        sockets = []
        ctx.route_web_socket("**/api/v1/ws", lambda ws: sockets.append(ws))
        page = ctx.new_page()
        page.set_default_timeout(8000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/#devices")
        page.get_by_label("E-posta", exact=True).fill(email)
        page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
        page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
        page.wait_for_load_state("networkidle")
        return ctx, page, sockets

    def request(ctx, path, method="GET", data=None):
        response = ctx.request.fetch(
            BASE + "/api/v1" + path, method=method, data=data, headers={"X-Netrix-Request": "1"}
        )
        assert response.ok, (response.status, response.text())
        return response.json() if response.status != 204 else None

    def capture(page, name):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))"
        )
        assert not reports[name], (name, reports[name])
        page.screenshot(path=str(OUT / (name + ".png")))

    owner, root, _ = login("alisan.yildirim@fbu.edu.tr")
    for account in request(owner, "/users")["items"]:
        if account["email"] in ("admin@example.test", "ssh-viewer@example.test"):
            request(
                owner,
                f"/users/{account['id']}/roles",
                "PUT",
                {
                    "role": account["role"],
                    "ssh_access": account["email"] == "ssh-viewer@example.test",
                },
            )
    root.goto(BASE + "/#users")
    root.wait_for_load_state("networkidle")
    root.get_by_role("button", name="Admin Without SSH rollerini düzenle", exact=True).click()
    editor = root.get_by_role("dialog", name="Kullanıcı rollerini düzenle", exact=True)
    role = editor.get_by_role("combobox", name="Uygulama rolü", exact=True)
    ssh = editor.get_by_role("checkbox", name="SSH bağlantısı", exact=True)
    for value in ("admin", "operator", "viewer", "admin"):
        role.select_option(value)
        expect(ssh).not_to_be_checked()
        expect(ssh).to_be_enabled()
    for width, height in ((1440, 1000), (375, 812)):
        root.set_viewport_size({"width": width, "height": height})
        for mode in ("light", "dark"):
            root.evaluate("m=>document.documentElement.dataset.theme=m", mode)
            field = role.bounding_box()
            box = editor.locator("fieldset").bounding_box()
            assert abs(field["x"] - box["x"]) < 1 and abs(field["width"] - box["width"]) < 1
            capture(root, f"role-editor-{width}-{mode}")
    ssh.check()
    editor.get_by_role("button", name="Rolleri kaydet", exact=True).click()
    expect(editor).not_to_be_visible()
    users = request(owner, "/users")["items"]
    admin = next(u for u in users if u["email"] == "admin@example.test")
    assert admin["role"] == "admin" and admin["ssh_access"]
    request(owner, f"/users/{admin['id']}/roles", "PUT", {"role": "admin", "ssh_access": False})
    root.set_viewport_size({"width": 1440, "height": 1000})
    root.reload()
    root.wait_for_load_state("networkidle")
    root.get_by_role("button", name="Super Owner rollerini düzenle", exact=True).click()
    expect(role).to_have_value("super_admin")
    expect(role).to_be_disabled()
    expect(ssh).to_be_checked()
    expect(ssh).to_be_disabled()
    editor.get_by_role("button", name="Vazgeç", exact=True).click()

    for email, allowed, admin_access in (
        ("admin@example.test", False, True),
        ("operator@example.test", False, False),
        ("viewer@example.test", False, False),
        ("ssh-viewer@example.test", True, False),
        ("alisan.yildirim@fbu.edu.tr", True, True),
    ):
        ctx, page, sockets = login(email)
        expect(page.get_by_role("button", name="SW-01 SSH bağlantısı", exact=True)).to_have_count(
            1 if allowed else 0
        )
        if not allowed:
            assert ctx.request.get(BASE + "/api/v1/access/ssh-profiles").status == 403
        for width, height in ((1440, 1000), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            if width < 1024:
                page.get_by_role("button", name="Menüyü aç", exact=True).click()
            page.get_by_role("button", name="Profil", exact=True).click()
            profile = page.get_by_role("dialog", name="Profil", exact=True)
            expect(profile.get_by_role("button", name="SSH Bağlantısı", exact=True)).to_have_count(
                1 if allowed else 0
            )
            expect(profile.get_by_role("button", name="Cihaz grupları", exact=True)).to_have_count(
                1 if allowed else 0
            )
            profile.get_by_role("button", name="Özellikler", exact=True).click()
            expect(profile.get_by_text("Hazır komutlar", exact=True)).to_have_count(1 if allowed else 0)
            expect(profile.get_by_text("Oturum şeridi", exact=True)).to_have_count(1 if allowed else 0)
            for mode in ("light", "dark"):
                page.evaluate("m=>document.documentElement.dataset.theme=m", mode)
                capture(page, f"profile-{email.split('@')[0]}-{width}-{mode}")
            profile.get_by_role("button", name="Pencereyi kapat", exact=True).click()
        if email == "ssh-viewer@example.test":
            target = next(u for u in request(owner, "/users")["items"] if u["email"] == email)
            request(owner, f"/users/{target['id']}/roles", "PUT", {"role": "viewer", "ssh_access": False})
            sockets[-1].send(json.dumps({"type": "refresh"}))
            expect(page.get_by_role("button", name="SW-01 SSH bağlantısı", exact=True)).to_have_count(
                0, timeout=10000
            )
        page.goto(BASE + "/#users")
        page.wait_for_load_state("networkidle")
        if admin_access:
            expect(page.get_by_role("heading", name="Ekip & yetkiler", exact=True)).to_be_visible()
            controls = page.get_by_role("button", name="rollerini düzenle", exact=False)
            if email == "admin@example.test":
                expect(controls).to_have_count(0)
                page.get_by_role("button", name="Yeni kayıt", exact=True).click()
                expect(page.get_by_label("Uygulama rolü", exact=True)).to_have_count(0)
                expect(page.get_by_label("SSH bağlantısı rolü", exact=True)).to_have_count(0)
                # Downgrading the active administrator also removes an already-open form.
                request(owner, f"/users/{admin['id']}/roles", "PUT", {"role": "viewer", "ssh_access": False})
                sockets[-1].send(json.dumps({"type": "refresh"}))
                expect(page.get_by_role("dialog")).to_have_count(0, timeout=10000)
                expect(page.get_by_role("heading", name="Ekip & yetkiler", exact=True)).to_have_count(0)
                request(owner, f"/users/{admin['id']}/roles", "PUT", {"role": "admin", "ssh_access": False})
        else:
            expect(page.get_by_role("heading", name="Ekip & yetkiler", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Cihaz ekle", exact=True)).to_have_count(
                0 if email.startswith(("viewer", "ssh-viewer")) else 1
            )
        if not allowed or email == "ssh-viewer@example.test":
            paths = []
            ctx.on("request", lambda r: paths.append(r.url))
            missing = "00000000-0000-0000-0000-000000000000"
            for route in (f"terminal/{missing}", f"batch/{missing}", f"batch/draft/{missing}"):
                page.goto(BASE + "/" + route)
                expect(page.get_by_text("Bu alana erişim yetkiniz bulunmuyor.", exact=True)).to_be_visible()
                expect(page.get_by_role("dialog")).to_have_count(0)
            assert not any(
                "/api/v1/access/" in url and not url.endswith("/access/preferences") for url in paths
            ), paths
        ctx.close()
    assert not errors, errors
    (OUT / "checks.json").write_text(json.dumps({"accessibility": reports, "errors": errors}, indent=2))
    print(
        "24 desktop/mobile accessibility checks passed; owner-only assignments, unchecked admin SSH, role-aware controls/profile/preferences, safe deep links, and live revocation verified."
    )
    browser.close()
