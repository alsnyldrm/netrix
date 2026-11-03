"""Actual API save, calendar fields, VLAN selection, execution history and responsive UI."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8225"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, timezone_id="UTC", bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#ipam-settings")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("heading", name="VLAN tam tarama zamanlaması", exact=True).wait_for()
    page.get_by_role("button", name="Yeni grup", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Grup adı", exact=False).fill("Gece Sunucu Taraması")
    dialog.get_by_label("Açıklama", exact=True).fill("Sunucu ve yönetim VLAN grubu")
    dialog.get_by_label("Tekrarlama", exact=True).select_option("monthly")
    dialog.get_by_label("Tekrar aralığı", exact=True).fill("2")
    dialog.get_by_label("Başlangıç tarihi ve saati", exact=False).fill("2030-01-31T02:30")
    dialog.get_by_label("Toplam çalışma sayısı", exact=True).fill("3")
    # Nothing can run until the user explicitly chooses the VLAN members.
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("en az bir VLAN")
    search = dialog.get_by_role("searchbox", name="VLAN ara", exact=True)
    search.fill("SERVER")
    dialog.get_by_role("button", name="Aramadakileri seç", exact=True).click()
    search.fill("NETWORK")
    dialog.get_by_role("checkbox", name="VLAN-10 / NETWORK", exact=False).check()
    search.fill("CIDR eksik")
    expect(dialog.get_by_role("checkbox", name="VLAN-30", exact=False)).to_be_disabled()
    search.fill("")

    def check(name):
        for width, height in ((1440, 1000), (375, 812), (812, 375)):
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                if page.get_by_role("dialog").count():
                    page.get_by_role("dialog").evaluate("e=>e.scrollTop=0")
                    assert page.get_by_role("dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
                assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                violations = page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                assert not violations, (name, width, theme, violations)
                page.screenshot(path=f"/tmp/netrix-scans-{name}-{width}-{theme}.png")
        page.set_viewport_size({"width": 1440, "height": 1000})

    check("form")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/api/v1/ipam/scan-groups")
    ) as response:
        dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    assert response.value.ok, response.value.text()
    group = response.value.json()
    assert group["frequency"] == "monthly" and group["repeat_every"] == 2 and group["run_limit"] == 3
    assert group["start_at"].startswith("2030-01-30T23:30") and len(group["vlan_ids"]) == 2
    expect(page.get_by_role("heading", name=group["name"], exact=True)).to_be_visible()
    page.get_by_text("2 VLAN", exact=True).click()
    expect(page.get_by_role("listitem").filter(has_text="SERVER")).to_be_visible()
    check("groups")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Düzenle", exact=True).click()
    expect(dialog.get_by_label("Başlangıç tarihi ve saati", exact=False)).to_have_value("2030-01-31T02:30")
    expect(dialog.get_by_label("Tekrar aralığı", exact=True)).to_have_value("2")
    dialog.get_by_role("checkbox", name="Zamanlama etkin", exact=True).uncheck()
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(page.get_by_text("Duraklatıldı", exact=True)).to_be_visible()
    # Re-enable, dispatch the due slot in the disposable server and verify durable job status.
    page.get_by_role("button", name="Düzenle", exact=True).click()
    dialog.get_by_role("checkbox", name="Zamanlama etkin", exact=True).check()
    dialog.get_by_role("button", name="Grubu kaydet", exact=True).click()
    expect(page.get_by_text("Zamanlandı", exact=True)).to_be_visible()
    dispatched = page.request.post(
        BASE + "/fixture/dispatch",
        params={"at": group["start_at"]},
        headers={"X-Netrix-Request": "1", "Origin": BASE},
    )
    assert dispatched.ok, dispatched.text()
    page.get_by_role("button", name="Tarama geçmişi", exact=True).click()
    expect(dialog.get_by_text("Kuyrukta", exact=True)).to_have_count(2)
    check("history")
    page.keyboard.press("Escape")
    page.get_by_role("button", name=group["name"] + " grubunu sil", exact=True).click()
    dialog.get_by_role("button", name="Grubu sil", exact=True).click()
    expect(page.get_by_role("heading", name=group["name"], exact=True)).to_have_count(0)
    assert not page.request.get(BASE + "/api/v1/ipam/scan-groups").json()["items"]
    assert not errors, errors
    print(
        "PASS: settings menu, VLAN groups, monthly recurrence, Istanbul input under UTC browser, pause/resume, durable queue history, desktop/mobile and both themes with axe"
    )
    browser.close()
