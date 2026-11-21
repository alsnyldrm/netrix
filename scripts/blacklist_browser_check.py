"""Exercise blacklist drafts and alignment against a disposable fixture."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "blacklist"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8291/#blacklist-groups")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_text("Henüz ACL grubu yok", exact=True)).to_be_visible()

    def check(name):
        assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth"), name
        dialog = page.get_by_role("dialog")
        if dialog.count():
            assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), name
        page.add_script_tag(path=str(ROOT / "frontend/node_modules/axe-core/axe.min.js"))
        violations = page.evaluate("""async () => (await axe.run(document, {
          runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','wcag22aa']}
        })).violations.map(v => ({id:v.id,targets:v.nodes.map(n=>n.target)}))""")
        reports[name] = violations
        page.screenshot(path=str(ARTIFACTS / (name + ".png")), full_page=True)

    def sizes(state):
        for width in (1440, 768, 375):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
                page.evaluate("theme => document.documentElement.dataset.theme=theme", theme)
                check(f"{state}-{width}-{theme}")
        page.set_viewport_size({"width": 1440, "height": 1000})

    sizes("groups-empty")
    page.get_by_role("button", name="Yeni ACL grubu", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("checkbox")).to_have_count(6)
    expect(dialog).not_to_contain_text("Fixture gateway")
    dialog.get_by_label("Grup adı", exact=True).fill("Kampüs erişim")
    for control in dialog.get_by_role("checkbox").all():
        control.check()
    for family in ("aos_switch", "aos_cx", "aruba_os", "comware_1950"):
        dialog.locator(f'input[name="{family}-name"]').fill("BLOCKED_IPS")
    dialog.locator('select[name="aos_switch-type"]').select_option("extended")
    dialog.locator('input[name="comware_1950-number"]').fill("3001")
    dialog.locator('select[name="comware_1950-type"]').select_option("advanced")
    dialog.locator('input[name="comware_1950-number"]').fill("3001")
    sizes("group-editor")
    page.set_viewport_size({"width": 1440, "height": 1000})
    for fieldset in dialog.locator(".blacklist-profile").all():
        fields = fieldset.locator("input, select").evaluate_all(
            "els=>els.map(e=>{const r=e.getBoundingClientRect(); return {y:r.y,h:r.height}})"
        )
        assert max(item["y"] for item in fields) - min(item["y"] for item in fields) <= 1, fields
        assert max(item["h"] for item in fields) - min(item["h"] for item in fields) <= 1, fields
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page.locator(".blacklist-panel tbody tr")).to_have_count(1)
    sizes("groups-populated")
    page.get_by_role("button", name="Kampüs erişim grubunu düzenle", exact=True).click()
    expect(page.get_by_role("dialog").get_by_role("checkbox").first).to_be_checked()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    # An IP can refer to two groups containing the same devices and ACLs.
    group = page.request.get("http://127.0.0.1:8291/api/v1/blacklist/groups").json()["items"][0]
    second = page.request.post(
        "http://127.0.0.1:8291/api/v1/blacklist/groups",
        headers={"X-Netrix-Request": "1"},
        data={
            "name": "Ortak erişim",
            "device_ids": group["device_ids"],
            "profiles": group["profiles"],
        },
    )
    assert second.status == 201, second.text()
    page.goto("http://127.0.0.1:8291/#blacklist")
    expect(page.get_by_text("Henüz IP taslağı yok", exact=True)).to_be_visible()
    page.get_by_role("button", name="Yeni IP taslağı", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("IP adresi", exact=True).fill("192.0.2.200")
    dialog.get_by_label("Açıklama (isteğe bağlı)", exact=True).fill("Tarayıcı doğrulama kaydı")
    for control in dialog.get_by_role("checkbox").all():
        control.check()
    sizes("entry-editor")
    dialog.get_by_role("button", name="Taslağı kaydet", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page.locator(".blacklist-panel tbody tr")).to_have_count(1)
    sizes("entries-populated")
    page.get_by_role("button", name="192.0.2.200 hedeflerini önizle", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.locator(".blacklist-targets li")).to_have_count(6)
    expect(dialog).to_contain_text("Cihazlara gönderim henüz etkin değil.")
    sizes("preview")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="192.0.2.200 taslağını düzenle", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("IP adresi", exact=True)).to_have_value("192.0.2.200")
    for checkbox in dialog.get_by_role("checkbox").all():
        expect(checkbox).to_be_checked()
    page.keyboard.press("Escape")
    page.reload()
    expect(page.locator(".blacklist-panel tbody tr")).to_have_count(1)
    assert not errors and not any(reports.values()), {"page_errors": errors, "axe": reports}
    print(
        json.dumps({"views": len(reports), "page_errors": errors, "axe": reports, "multi_group_dedup": True})
    )
    browser.close()
