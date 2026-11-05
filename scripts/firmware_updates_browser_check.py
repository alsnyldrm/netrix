"""Exercise status, exact bulk selection, grouped planning, safety preview and responsive alignment."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:" + os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8278")
Path("artifacts").mkdir(exist_ok=True)
reports, errors = {}, []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1100}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#firmware-devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.locator(".fw-devices-table tbody tr")).to_have_count(50)
    menu = page.locator(".nav-group").filter(has=page.get_by_role("button", name="Firmware", exact=True))
    group_toggle = menu.get_by_role("button", name="Firmware", exact=True)
    if group_toggle.get_attribute("aria-expanded") != "true":
        group_toggle.click()
    assert menu.locator(".nav-item").all_text_contents() == [
        "Cihazlar",
        "Güncelleme planları",
        "Firmware deposu",
        "Gruplar",
        "İşlem geçmişi",
    ]

    def check(name):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        alignment = page.locator(".fw-table").evaluate_all("""tables => tables.flatMap(t => {
          const headers = [...t.querySelectorAll('th')]; const failures = [];
          for (const row of t.querySelectorAll('tbody tr')) {
            const y = [];
            [...row.cells].forEach((cell, i) => { const text = cell.querySelector('.fw-cell-primary'); if (!text) return;
              const a = text.getBoundingClientRect(), h = headers[i].getBoundingClientRect(); y.push(a.y);
              if (Math.abs(a.x - h.x - parseFloat(getComputedStyle(headers[i]).paddingLeft)) > 1) failures.push(i);
            }); if (y.length && Math.max(...y) - Math.min(...y) > 1) failures.push('row');
          } return failures;
        })""")
        assert not alignment, (name, alignment)
        summary_alignment = page.locator(".fw-device-summary > *").evaluate_all("""cards => cards.flatMap(card => {
          const x = card.getBoundingClientRect().x + parseFloat(getComputedStyle(card).paddingLeft);
          return [...card.querySelectorAll('span,b')].filter(child => Math.abs(child.getBoundingClientRect().x - x) > 2).map(child => child.textContent);
        })""")
        assert not summary_alignment, (name, summary_alignment)

        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
        )
        assert not reports[name], (name, reports[name])
        page.screenshot(path=f"artifacts/firmware-updates-{name}.png", full_page=True)

    expect(page.get_by_role("button", name="Güncel değil 996", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Güncel 3", exact=True)).to_be_visible()
    expect(page.get_by_label("Fixture 0001 cihazını seç", exact=True)).to_be_disabled()
    expect(page.get_by_label("Fixture 0002 cihazını seç", exact=True)).to_be_disabled()
    expect(page.get_by_label("Fixture 0003 cihazını seç", exact=True)).to_be_disabled()
    page.get_by_label("Bu sayfadaki güncel olmayan cihazları seç", exact=True).check()
    expect(page.locator(".fw-device-selection")).to_contain_text("46 cihaz seçildi")
    page.get_by_role("button", name="Seçimi temizle", exact=True).click()
    for number in (0, 5):
        page.get_by_label(f"Fixture {number:04} cihazını seç", exact=True).check()
    page.get_by_role("button", name="Güncelle", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("status").filter(has_text="2 cihaz taslak plana alınacak.")).to_be_visible()
    expect(dialog.get_by_label("Firmware grubu", exact=True).first).to_be_disabled()
    assert dialog.get_by_label("Firmware grubu", exact=True).count() == 2
    # Switching steps while a preview exists must not render stale per-step data.
    dialog.get_by_role("button", name="Aşama ekle", exact=True).click()
    expect(dialog.get_by_role("button", name="Taslak oluştur", exact=True)).to_be_disabled()
    dialog.get_by_role("button", name="Aşama 3 kaldır", exact=True).click()
    expect(dialog.get_by_role("status").filter(has_text="2 cihaz taslak plana alınacak.")).to_be_visible()
    for width, theme in ((w, t) for w in (1440, 1024, 768, 375) for t in ("light", "dark")):
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        check(f"selection-plan-{width}-{theme}")
    dialog.get_by_label("Plan adı", exact=True).fill("Exact selected devices")
    dialog.get_by_label(
        "Üreticinin model, sürüm geçişi ve BootROM gereksinimlerini doğruladım.", exact=True
    ).check()
    dialog.get_by_role("button", name="Taslak oluştur", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("Exact selected devices")
    expect(page.get_by_role("dialog").locator("tbody tr")).to_have_count(2)
    expect(page.get_by_role("dialog").locator("tbody")).to_contain_text("Fixture 0000")
    expect(page.get_by_role("dialog").locator("tbody")).to_contain_text("Fixture 0005")
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1440, "height": 1100})
    page.get_by_role("button", name="Güncel değil 996", exact=True).click()
    expect(page.locator(".fw-update-group")).to_have_count(4)
    group = page.get_by_role("region", name="Erişim güncelleme grubu", exact=True)
    group.get_by_text("Cihazları göster", exact=True).click()
    expect(group.locator("li")).to_have_count(1)
    expect(group.locator("li")).to_contain_text("Fixture 0000")
    for width, theme in ((w, t) for w in (1440, 1024, 768, 375) for t in ("light", "dark")):
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        check(f"outdated-groups-{width}-{theme}")
    page.get_by_label("Erişim güncelleme grubu grubunu seç", exact=True).check()
    page.get_by_role("button", name="Seçili grupları planla", exact=True).click()
    expect(
        page.get_by_role("dialog").get_by_role("status").filter(has_text="1 cihaz taslak plana alınacak.")
    ).to_be_visible()
    page.get_by_role("dialog").get_by_role("button", name="Vazgeç", exact=True).click()
    page.get_by_role("button", name="Güncel 3", exact=True).click()
    expect(page.locator(".fw-devices-table tbody tr")).to_have_count(3)
    expect(page.locator(".fw-update-current")).to_have_count(3)
    for width, theme in ((w, t) for w in (1440, 1024, 768, 375) for t in ("light", "dark")):
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        check(f"current-devices-{width}-{theme}")
    page.set_viewport_size({"width": 1440, "height": 1100})
    page.goto(BASE + "/#firmware-plans")
    page.get_by_role("button", name="Plan oluştur", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Firmware grubu", exact=True).select_option(label="Erişim güncelleme grubu · 4 cihaz")
    dialog.get_by_label("Firmware imajı", exact=True).select_option(
        label="Aruba comparison image · WC.16.11.0026"
    )
    dialog.get_by_label("İşlem", exact=True).select_option("upgrade")
    expect(dialog).to_contain_text("1 aynı sürüm · 1 daha yeni · 1 karşılaştırılamıyor")
    expect(dialog.get_by_role("status").filter(has_text="1 cihaz taslak plana alınacak.")).to_be_visible()
    check("group-preview")
    for width, theme in ((w, t) for w in (1440, 375) for t in ("light", "dark")):
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
        page.goto(BASE + "/#firmware-images")
        expect(page.locator(".fw-images-table tbody")).to_contain_text(
            "Model ve sürüm serisi otomatik doğrulanır"
        )
        assert "JL675A" not in page.locator(".fw-images-table tbody").inner_text()
        check(f"legacy-image-family-{width}-{theme}")
        page.get_by_role("button", name="Fixture firmware", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        assert "Mevcut model kısıtları" not in page.get_by_role("dialog").inner_text()
        check(f"legacy-image-detail-{width}-{theme}")
        page.keyboard.press("Escape")
    assert not errors, errors
    Path("artifacts/firmware-updates-browser-report.json").write_text(
        json.dumps({"views": len(reports), "axe": reports, "errors": errors}, indent=2)
    )
    print(
        json.dumps(
            {
                "views": len(reports),
                "axe_violations": sum(len(v) for v in reports.values()),
                "page_errors": errors,
                "bulk_selection": "exactly two targets",
                "group_filter": "older only; equal/newer/unknown excluded",
            }
        )
    )
    browser.close()
