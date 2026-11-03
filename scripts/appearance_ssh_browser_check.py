"""Isolated real HTTP workspace: 5 layouts x 10 palettes, account controls and SSH group routing."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
ARTIFACTS = Path("artifacts/appearance-ssh")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
THEMES = ["atlas", "orbit", "terminal", "panorama", "focus"]
PALETTES = ["cobalt", "teal", "violet", "amber", "forest", "slate", "rose", "cyan", "orange", "indigo"]
reports, errors, checks = {}, [], 0
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)

    def terminal_socket(ws):
        ws.send(json.dumps({"type": "status", "status": "connected"}))
        ws.send(json.dumps({"type": "output", "data": "NETRIX browser terminal fixture\r\nSW-01# "}))

    context.route_web_socket("**/api/v1/access/sessions/*/ws", terminal_socket)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
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

    def open_profile():
        if page.viewport_size["width"] < 1024:
            page.get_by_role("button", name="Menüyü aç", exact=True).click()
        page.get_by_role("button", name="Profil", exact=True).click()
        return page.get_by_role("dialog", name="Profil", exact=True)

    def settle():
        # Wait for actual used colors, not just data attributes or a fixed delay.
        page.wait_for_function(
            """() => {
          const s=getComputedStyle(document.documentElement);
          const rgb = hex => {let v=hex.trim().replace('#',''); if(v.length===3) v=v.split('').map(c=>c+c).join(''); return `rgb(${[0,2,4].map(i=>parseInt(v.slice(i,i+2),16)).join(', ')})`;};
          const foreground=rgb(s.getPropertyValue('--text'));
          return s.color===foreground && s.backgroundColor===rgb(s.getPropertyValue('--bg')) && Array.from(document.querySelectorAll('dialog[open] > .dialog-header h2')).every(e=>getComputedStyle(e).color===foreground);
        }""",
            timeout=5000,
        )

    def capture(name, axe=True):
        global checks
        settle()
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        if axe:
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            reports[name] = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))"
            )
        page.screenshot(path=str(ARTIFACTS / (name + ".png")))
        checks += 1
        (ARTIFACTS / "partial.json").write_text(json.dumps(reports, indent=2))

    profile = open_profile()
    profile.get_by_role("button", name="Cihaz grupları", exact=True).click()
    profile.get_by_role("button", name="Grup oluştur", exact=True).click()
    group = page.get_by_role("dialog", name="Yeni cihaz grubu", exact=True)
    group.get_by_label("Grup adı", exact=True).fill("Laboratuvar")
    group.get_by_role("button", name="Filtreler", exact=True).click()
    filters = page.get_by_role("dialog", name="Filtreler", exact=True)
    filters.get_by_label("Koşul 1 alanı", exact=True).select_option("model")
    filters.get_by_label("Koşul 1 değeri", exact=True).fill("CX6200")
    filters.get_by_role("button", name="Filtreleri uygula", exact=True).click()
    group.get_by_role("button", name="Tüm eşleşenleri seç (150)", exact=True).click()
    expect(group.get_by_role("heading", name="Cihazlar")).to_contain_text("130 seçili")
    expect(group.get_by_role("status")).to_contain_text("20 cihaz başka gruplarda")
    group.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(profile.locator(".access-group-cards")).to_contain_text("130 cihaz")
    profile.get_by_role("button", name="Grup oluştur", exact=True).click()
    group = page.get_by_role("dialog", name="Yeni cihaz grubu", exact=True)
    group.get_by_label("Tüm alanlarda ara", exact=True).fill("SW-25")
    expect(group.locator(".group-device-list > label")).to_have_count(1)
    expect(group.locator(".group-device-list input")).to_be_disabled()
    expect(group.locator(".group-device-list")).to_contain_text("Laboratuvar")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for mode in ("light", "dark"):
            page.evaluate("m=>document.documentElement.dataset.theme=m", mode)
            capture(f"duplicate-group-{width}-{mode}")
    group.get_by_role("button", name="Vazgeç", exact=True).click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    profile.get_by_role("button", name="SSH Bağlantısı", exact=True).click()
    expect(profile.locator(".ssh-profile-cards article")).to_have_count(1)
    profile.get_by_role("button", name="Bağlantı ekle", exact=True).click()
    connection = page.get_by_role("dialog", name="Yeni SSH bağlantısı", exact=True)
    connection.get_by_label("Bağlantı adı", exact=True).fill("Laboratuvar hesabı")
    connection.get_by_label("Kullanıcı adı", exact=True).fill("lab-admin")
    connection.get_by_label("Şifre", exact=True).fill("browser-new-secret")
    connection.locator(".ssh-group-options label").filter(has_text="Laboratuvar").locator("input").check()
    expect(
        connection.locator(".ssh-group-options label").filter(has_text="Fixture cihazları").locator("input")
    ).to_be_disabled()
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for mode in ("light", "dark"):
            page.evaluate("m=>document.documentElement.dataset.theme=m", mode)
            capture(f"ssh-connection-form-{width}-{mode}")
    connection.get_by_role("button", name="Bağlantıyı kaydet", exact=True).click()
    expect(profile.locator(".ssh-profile-cards article")).to_have_count(2)
    expect(profile.locator(".ssh-profile-cards")).to_contain_text("Laboratuvar hesabı")
    profiles = request("/access/ssh-profiles")["items"]
    assert "browser-new-secret" not in json.dumps(profiles)
    selected = next(v for v in profiles if v["name"] == "Laboratuvar hesabı")
    group_id = next(g["id"] for g in request("/access/groups")["items"] if g["name"] == "Laboratuvar")
    assert selected["group_ids"] == [group_id]
    profile.get_by_role("button", name="Laboratuvar hesabı düzenle", exact=True).click()
    connection = page.get_by_role("dialog", name="SSH bağlantısını düzenle", exact=True)
    expect(connection.get_by_label("Şifre", exact=True)).to_have_value("")
    connection.get_by_label("Port", exact=True).fill("2222")
    connection.get_by_role("button", name="Bağlantıyı kaydet", exact=True).click()
    profile.get_by_role("button", name="Bağlantı ekle", exact=True).click()
    connection = page.get_by_role("dialog", name="Yeni SSH bağlantısı", exact=True)
    connection.get_by_label("Bağlantı adı", exact=True).fill("Yedek hesap")
    connection.get_by_label("Kullanıcı adı", exact=True).fill("second-admin")
    connection.get_by_label("Şifre", exact=True).fill("browser-second-secret")
    expect(
        connection.locator(".ssh-group-options label").filter(has_text="Laboratuvar").locator("input")
    ).to_be_disabled()
    connection.get_by_role("button", name="Bağlantıyı kaydet", exact=True).click()
    expect(profile.locator(".ssh-profile-cards article")).to_have_count(3)
    expect(profile.locator(".ssh-profile-cards")).to_contain_text("Grup atanmamış")
    # Each persisted design changes the actual shell; every palette changes its surfaces.
    for design in THEMES:
        page.set_viewport_size({"width": 1440, "height": 1000})
        profile.get_by_role("button", name="Tema", exact=True).click()
        profile.locator(".theme-option").filter(
            has_text={
                "atlas": "Atlas",
                "orbit": "Orbit",
                "terminal": "Terminal",
                "panorama": "Panorama",
                "focus": "Focus",
            }[design]
        ).click()
        expect(page.locator("html")).to_have_attribute("data-design", design)
        expect(profile.get_by_role("status")).to_contain_text("Tercihleriniz kaydedildi")
        assert request("/access/preferences")["design"] == design
        capture(f"theme-picker-{design}")
        heights = profile.locator(".theme-option").evaluate_all(
            "es=>es.map(e=>e.getBoundingClientRect().height)"
        )
        assert max(heights) - min(heights) < 1, (design, heights)
        profile.get_by_role("button", name="Pencereyi kapat", exact=True).click()
        signatures = []
        for width in (1440, 375):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
            for mode in ("light", "dark"):
                page.evaluate("m=>document.documentElement.dataset.theme=m", mode)
                surfaces = []
                for palette in PALETTES:
                    page.evaluate("p=>document.documentElement.dataset.palette=p", palette)
                    # Flush style and layout before checking runtime roles.
                    page.evaluate("() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                    state = page.evaluate("""() => {
                      const s=getComputedStyle(document.documentElement),main=document.querySelector('main').getBoundingClientRect();
                      const luminance = hex => { const h=hex.trim().replace('#',''); const full=h.length===3?h.split('').map(c=>c+c).join(''):h;return [0,2,4].map(i=>parseInt(full.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0); };
                      const pairs=[['text','surface'],['text-2','surface-2'],['text-3','surface-2'],['accent','surface-2'],['accent-soft-text','accent-soft'],['on-primary','primary'],['on-primary-hover','primary-hover']];
                      const contrast=pairs.map(([a,b])=>{const x=luminance(s.getPropertyValue('--'+a)),y=luminance(s.getPropertyValue('--'+b));return {a,b,ratio:(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};});
                      return { contrast,bg:s.getPropertyValue('--bg'), surface:s.getPropertyValue('--surface'), accent:s.getPropertyValue('--accent'), primary:s.getPropertyValue('--primary'), left:main.left, right:main.right, width:innerWidth };
                    }""")
                    assert state["left"] >= -1 and state["right"] <= width + 1, (design, mode, width, state)
                    assert all(pair["ratio"] >= 4.5 for pair in state["contrast"]), (
                        design,
                        width,
                        mode,
                        palette,
                        state["contrast"],
                    )
                    surfaces.append((state["bg"], state["surface"], state["primary"]))
                    checks += 1
                assert len(set(surfaces)) == 10, (design, width, mode, surfaces)
                page.evaluate("()=>document.documentElement.dataset.palette='amber'")
                capture(f"shell-{design}-{width}-{mode}")
                profile = open_profile()
                profile.get_by_role("button", name="SSH Bağlantısı", exact=True).click()
                capture(f"ssh-list-{design}-{width}-{mode}")
                profile.get_by_role("button", name="Laboratuvar hesabı düzenle", exact=True).click()
                capture(f"ssh-form-{design}-{width}-{mode}")
                page.get_by_role("dialog", name="SSH bağlantısını düzenle", exact=True).get_by_role(
                    "button", name="Vazgeç", exact=True
                ).click()
                profile.get_by_role("button", name="Pencereyi kapat", exact=True).click()
                page.get_by_role("button", name="SW-01 SSH bağlantısı", exact=True).click()
                terminal = page.get_by_role("dialog", name="SW-01 SSH bağlantısı", exact=True)
                expect(terminal.locator(".ssh-state")).to_have_text("Bağlı")
                capture(f"terminal-{design}-{width}-{mode}")
                terminal.get_by_role("button", name="Tam ekran", exact=True).click()
                terminal.get_by_role("button", name="Pencereyi küçült", exact=True).click()
                terminal.get_by_role("button", name="Simge durumuna küçült", exact=True).click()
                page.get_by_role("button", name="SW-01 SSH oturumunu aç", exact=True).click()
                terminal.get_by_role("button", name="SSH bağlantısını kapat", exact=True).click()
        if design == "panorama":
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.get_by_role("button", name="Envanter", exact=True).click()
            expect(page.get_by_role("button", name="Cihaz envanteri", exact=True)).to_be_visible()
            capture("panorama-dropdown")
            page.keyboard.press("Escape")
            expect(page.get_by_role("button", name="Envanter", exact=True)).to_have_attribute(
                "aria-expanded", "false"
            )
        profile = open_profile()
    page.set_viewport_size({"width": 1440, "height": 1000})
    profile.get_by_role("button", name="Renk paleti", exact=True).click()
    expect(profile.locator(".palette-option")).to_have_count(10)
    for name, palette in zip(
        [
            "Teknik kobalt",
            "Atlantik",
            "Ametist",
            "Sarı kehribar",
            "Orman",
            "Grafit",
            "Yakut",
            "Buzul",
            "Bakır",
            "Gece irisi",
        ],
        PALETTES,
    ):
        profile.get_by_role("button", name=name, exact=True).click()
        expect(page.locator("html")).to_have_attribute("data-palette", palette)
        expect(profile.get_by_role("status")).to_contain_text("Tercihleriniz kaydedildi")
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        for mode in ("light", "dark"):
            page.evaluate("m=>document.documentElement.dataset.theme=m", mode)
            capture(f"palette-picker-{width}-{mode}")
    profile.get_by_role("button", name="Pencereyi kapat", exact=True).click()
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(page.locator("html")).to_have_attribute("data-design", "focus")
    expect(page.locator("html")).to_have_attribute("data-palette", "indigo")
    violations = {k: v for k, v in reports.items() if v}
    (ARTIFACTS / "report.json").write_text(
        json.dumps({"checks": checks, "violations": violations, "errors": errors}, indent=2)
    )
    browser.close()
    assert not errors, errors
    assert not violations, violations
print(json.dumps({"checks": checks, "accessibility_errors": 0, "browser_errors": 0}))
