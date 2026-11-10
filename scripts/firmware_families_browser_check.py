"""Real local uploads for four families; responsive, semantic and alignment checks."""

import hashlib
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:" + os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8291")
FAMILIES = [
    ("aos_s_54xx", "AOS Switch 54xx", "KB.16.11.0032", ".swi"),
    ("aos_s_29xx", "AOS Switch 29xx", "WC.16.11.0032", ".swi"),
    ("cx6100", "AOS-CX Switch 61xx", "PL.10.18.1010", ".swi"),
    ("hp1950", "HP Conware 7 1950", "R3507P10", ".ipe"),
]
RELEASE_NOTES = (
    "Yenilikler\n• SSH bağlantısı iyileştirildi.\n\nBilinen sorunlar: <script>alert('release')</script>\n"
    + "uzunsatır" * 30
)
Path("artifacts").mkdir(exist_ok=True)
reports, errors, posts = {}, [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1050}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "request",
        lambda r: (
            posts.append(r.post_data_json)
            if r.method == "POST" and r.url.endswith("/firmware/images")
            else None
        ),
    )
    page.goto(BASE + "/#firmware-images")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def check(name, upload=True):
        dialog = page.get_by_role("dialog")
        page.evaluate("() => document.fonts.ready")
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        assert dialog.locator('input[name="models"]').count() == 0
        assert "Uyumlu ürün kodları" not in dialog.inner_text()
        issues = dialog.evaluate("""d => {
          const failures=[];
          const family=d.querySelector('select[name="family"]'), version=d.querySelector('input[name="version"]');
          if (family && version) {
            const a=family.getBoundingClientRect(), b=version.getBoundingClientRect();
            if (b.x>a.x+1 && (Math.abs(b.y-a.y)>1 || Math.abs(b.height-a.height)>1)) failures.push('family/version baseline');
          }
          for (const e of d.querySelectorAll('input,select,textarea')) {
            const r=e.getBoundingClientRect();
            if (r.width && (r.left<d.getBoundingClientRect().left || r.right>d.getBoundingClientRect().right)) failures.push('field overflow');
          }
          const buttons=[...d.querySelectorAll('.fw-form-actions button')].map(e=>e.getBoundingClientRect());
          if (buttons.length>1 && (Math.abs(buttons[0].y-buttons[1].y)>1 || Math.abs(buttons[0].height-buttons[1].height)>1)) failures.push('action alignment');
          if (buttons.some(b=>b.bottom>d.getBoundingClientRect().bottom-2)) failures.push('actions clipped');
          return failures;
        }""")
        assert not issues, (name, issues)
        if upload:
            expect(dialog.get_by_label("Release notları", exact=True)).to_be_visible()
        assert dialog.locator(".fw-notes script").count() == 0
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
        )
        page.screenshot(path=f"artifacts/firmware-families-{name}.png", full_page=True)

    for family, label, version, extension in FAMILIES:
        page.get_by_role("button", name="Dosya yükle", exact=True).click()
        dialog = page.get_by_role("dialog")
        select = dialog.get_by_label("Cihaz ailesi", exact=True)
        expect(select).to_be_visible()
        assert select.locator("option").all_text_contents() == ["Cihaz ailesi seçin"] + [
            f[1] for f in FAMILIES
        ], select.locator("option").all_text_contents()
        select.select_option(family)
        dialog.get_by_label("Hedef sürüm", exact=True).fill(version)
        assert dialog.get_by_label("Hedef sürüm", exact=True).evaluate("(e)=>e.checkValidity()")
        dialog.get_by_label("Dosya adı için açıklama", exact=True).fill("Family upload " + family)
        dialog.get_by_label("Release notları", exact=True).fill(RELEASE_NOTES)
        content = ("family fixture " + family).encode()
        dialog.get_by_label("Üreticinin yayımladığı SHA-256", exact=True).fill(
            hashlib.sha256(content).hexdigest()
        )
        file = dialog.get_by_label("Firmware dosyası", exact=True)
        assert file.get_attribute("accept") == extension
        file.set_input_files(
            {"name": "family" + extension, "mimeType": "application/octet-stream", "buffer": content}
        )
        for width in (1440, 768, 375):
            page.set_viewport_size({"width": width, "height": 1050 if width == 1440 else 960})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                check(f"{family}-{width}-{theme}")
        if family == "aos_s_54xx":
            dialog.get_by_label("Hedef sürüm", exact=True).fill("WC.16.11.0032")
            assert not dialog.get_by_label("Hedef sürüm", exact=True).evaluate("(e)=>e.checkValidity()")
            assert not posts
            dialog.get_by_label("Hedef sürüm", exact=True).fill(version)
        if family == "hp1950":
            file.set_input_files(
                {"name": "wrong.swi", "mimeType": "application/octet-stream", "buffer": content}
            )
            count = len(posts)
            dialog.get_by_role("button", name="Dosyayı yükle", exact=True).click()
            expect(dialog.get_by_role("alert")).to_contain_text(".ipe")
            assert len(posts) == count
            check("wrong-extension-mobile")
            file.set_input_files(
                {"name": "family.ipe", "mimeType": "application/octet-stream", "buffer": content}
            )
        dialog.locator(".fw-upload-notes summary").click()
        dialog.get_by_label("Sürüm geçişi, BootROM ve kurtarma notları", exact=True).fill(
            "Fixture upgrade notes"
        )
        check(f"{family}-notes-mobile")
        dialog.get_by_role("button", name="Dosyayı yükle", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        expect(page.locator(".fw-workspace tbody")).to_contain_text("Family upload " + family)
        assert posts[-1]["family"] == family and "models" not in posts[-1]
        assert posts[-1]["release_notes"] == RELEASE_NOTES
        assert page.request.get(BASE + "/api/v1/firmware/images").json()["total"] >= len(posts) + 1
        if family == "cx6100":
            page.get_by_role("button", name="Family upload cx6100", exact=True).click()
            notes = page.get_by_role("region", name="Release notları", exact=True)
            expect(notes.locator(".fw-notes")).to_have_text(RELEASE_NOTES)
            for width in (1440, 375):
                page.set_viewport_size({"width": width, "height": 1050 if width == 1440 else 960})
                for theme in ("light", "dark"):
                    page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                    check(f"release-detail-{width}-{theme}", upload=False)
            notes.get_by_role("button", name="Release notlarını düzenle", exact=True).click()
            edited = "Düzenlenen release notu\nSatır sonları korunur."
            notes.get_by_label("Release notları", exact=True).fill(edited)
            check("release-editor-mobile", upload=False)
            notes.get_by_role("button", name="Release notlarını kaydet", exact=True).click()
            expect(notes.get_by_role("status")).to_have_text("Release notları kaydedildi.")
            expect(notes.locator(".fw-notes")).to_have_text(edited)
            page.get_by_role("dialog").get_by_role("button", name="Kapat", exact=True).click()
            page.get_by_role("button", name="Family upload cx6100", exact=True).click()
            expect(page.get_by_role("region", name="Release notları").locator(".fw-notes")).to_have_text(
                edited
            )
            page.get_by_role("dialog").get_by_role("button", name="Kapat", exact=True).click()
        page.set_viewport_size({"width": 1440, "height": 1050})
    assert len(posts) == 4 and not errors, errors
    assert all(not issues for issues in reports.values()), reports
    Path("artifacts/firmware-families-browser.json").write_text(
        json.dumps({"views": len(reports), "axe": reports, "errors": errors, "uploads": len(posts)}, indent=2)
    )
    browser.close()
print(
    json.dumps(
        {
            "passed_views": len(reports),
            "real_uploads": len(posts),
            "axe_violations": 0,
            "javascript_errors": 0,
        }
    )
)
