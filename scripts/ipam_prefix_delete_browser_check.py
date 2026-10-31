"""Single and bulk prefix deletion against disposable browser fixtures only."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, reports = [], {}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_role("button", name="192.0.2.0/24", exact=True)).to_be_visible()
    vrf = page.request.get("http://127.0.0.1:8211/api/v1/vrfs").json()["items"][0]["id"]
    for cidr in ["198.51.100.0/24", "203.0.113.0/24"]:
        response = page.request.post(
            "http://127.0.0.1:8211/api/v1/prefixes",
            data={"cidr": cidr, "vrf_id": vrf},
            headers={"X-Netrix-Request": "1"},
        )
        assert response.status == 201, response.text()
    page.reload()
    page.get_by_role("button", name="198.51.100.0/24 sil", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("list", name="Silinecek ağ blokları")).to_contain_text("198.51.100.0/24")
    expect(dialog.get_by_text("0 IP kaydı", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Vazgeç", exact=True).click()
    expect(page.get_by_role("button", name="198.51.100.0/24", exact=True)).to_be_visible()
    page.get_by_role("button", name="198.51.100.0/24 sil", exact=True).click()
    dialog.get_by_role("button", name="Sil", exact=True).click()
    expect(page.get_by_role("button", name="198.51.100.0/24", exact=True)).not_to_be_visible()
    page.get_by_role("checkbox", name="Sayfadaki ağ bloklarını seç", exact=True).check()
    expect(page.get_by_text("2 ağ bloğu seçildi", exact=True)).to_be_visible()
    Path("artifacts").mkdir(exist_ok=True)

    def check(name):
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)"
        )
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        page.screenshot(path=f"artifacts/prefix-delete-{name}.png")

    for width, height in [(1440, 1000), (375, 812)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ["light", "dark"]:
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            check(f"table-{width}-{theme}")
    page.get_by_role("region", name="Seçilen ağ bloğu işlemleri", exact=True).get_by_role(
        "button", name="Sil", exact=True
    ).click()
    expect(dialog.get_by_role("list", name="Silinecek ağ blokları")).to_contain_text("192.0.2.0/24")
    expect(dialog.get_by_role("list", name="Silinecek ağ blokları")).to_contain_text("203.0.113.0/24")
    expect(dialog.get_by_text("Kapsamı boşalan entegrasyonlar devre dışı bırakılır.", exact=False)).to_be_visible()
    for width, height in [(1440, 1000), (375, 812)]:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ["light", "dark"]:
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
            check(f"confirm-{width}-{theme}")
    dialog.get_by_role("button", name="Sil", exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_text("0 ağ bloğu", exact=True)).to_be_visible()
    assert page.request.get("http://127.0.0.1:8211/api/v1/prefixes").json()["total"] == 0
    assert page.request.get("http://127.0.0.1:8211/api/v1/addresses").json()["total"] == 0
    assert not errors and not any(reports.values()), (errors, reports)
    print(
        json.dumps(
            {
                "single_delete_cancel_and_confirm": "PASS",
                "bulk_delete": "PASS",
                "axe": reports,
                "errors": errors,
            }
        )
    )
    browser.close()
