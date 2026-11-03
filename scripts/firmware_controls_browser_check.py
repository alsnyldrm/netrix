"""Plan list controls, exact force confirmation, live concurrency and retained deletion."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:" + os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8282")
Path("artifacts").mkdir(exist_ok=True)
reports, errors = {}, []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#firmware-plans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(
        page.get_by_role("button", name="Fixture live control planını zorla durdur", exact=True)
    ).to_be_enabled()

    def check(name):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        failures = page.locator(".fw-table").evaluate_all("""tables=>tables.flatMap(t=>{
          const headers=[...t.querySelectorAll('th')], failures=[];
          for(const row of t.querySelectorAll('tbody tr')){const origins=[];
            [...row.cells].forEach((cell,i)=>{const text=cell.querySelector('.fw-cell-primary');if(!text)return;
              const a=text.getBoundingClientRect(),h=headers[i].getBoundingClientRect();origins.push(a.y);
              if(Math.abs(a.x-h.x-parseFloat(getComputedStyle(headers[i]).paddingLeft))>1)failures.push('column '+i);
            });if(origins.length&&Math.max(...origins)-Math.min(...origins)>1)failures.push('row');
          }return failures;
        })""")
        assert not failures, (name, failures)
        if page.viewport_size["width"] >= 1400:
            assert page.locator(".fw-plans-table").evaluate_all(
                "tables=>tables.every(t=>t.scrollWidth<=t.parentElement.clientWidth+1)"
            ), (name, "desktop actions clipped")
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[name] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
        )
        assert not reports[name], (name, reports[name])
        page.screenshot(path=f"artifacts/firmware-controls-{name}.png", full_page=True)

    def variants(name):
        for width in (1440, 768, 375):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": width, "height": 1000})
                page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
                check(f"{name}-{width}-{theme}")

    variants("list")
    page.get_by_role("button", name="Plan oluştur", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Plan adı", exact=True).fill("Fixture ten selected")
    dialog.get_by_label("Grup içi eşzamanlı cihaz", exact=True).select_option("10")
    dialog.get_by_label("Firmware grubu", exact=True).select_option(label="Fixture group · 1 cihaz")
    dialog.get_by_label("Firmware imajı", exact=True).select_option(index=1)
    expect(dialog.get_by_role("button", name="Taslak oluştur", exact=True)).to_be_enabled()
    variants("ten-form")
    dialog.get_by_role("button", name="Taslak oluştur", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Planın eşzamanlı cihaz sayısı", exact=True)).to_have_value("10")
    dialog.get_by_label("Planın eşzamanlı cihaz sayısı", exact=True).select_option("6")
    dialog.get_by_role("button", name="Eşzamanlılığı kaydet", exact=True).click()
    expect(dialog.get_by_role("button", name="Eşzamanlılığı kaydet", exact=True)).to_be_disabled()
    variants("ten-detail")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Fixture live control planını zorla durdur", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("button", name="Zorla durdur", exact=True)).to_be_disabled()
    dialog.get_by_label("Onay için planın tam adı", exact=False).fill("wrong")
    expect(dialog.get_by_role("button", name="Zorla durdur", exact=True)).to_be_disabled()
    dialog.get_by_label("Onay için planın tam adı", exact=False).fill("Fixture live control")
    variants("force-confirm")
    dialog.get_by_role("button", name="Zorla durdur", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    response = page.request.get(BASE + "/api/v1/firmware/plans").json()
    live = next(row for row in response["items"] if row["name"] == "Fixture live control")
    assert (
        live["force_stop_requested"]
        and live["cancel_requested"]
        and live["counts"]["running"] == 1
        and live["counts"]["staged"] == 1
        and live["counts"]["cancelled"] == 1
    )
    page.get_by_role("button", name="Fixture soft control planını durdur", exact=True).click()
    variants("soft-confirm")
    page.get_by_role("dialog").get_by_role("button", name="Durdur", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    response = page.request.get(BASE + "/api/v1/firmware/plans").json()
    soft = next(row for row in response["items"] if row["name"] == "Fixture soft control")
    assert soft["cancel_requested"] and not soft["force_stop_requested"] and soft["counts"]["running"] == 1
    done = next(row for row in response["items"] if row["name"] == "Fixture done control")
    page.get_by_role("button", name="Fixture done control planını sil", exact=True).click()
    variants("delete-confirm")
    page.get_by_role("dialog").get_by_role("button", name="Sil", exact=True).click()
    expect(page.get_by_role("button", name="Fixture done control", exact=True)).to_have_count(0)
    history = page.request.get(BASE + f"/api/v1/firmware/history/{done['id']}")
    assert history.status == 200 and history.json()["name"] == "Fixture done control"
    assert not errors, errors
    Path("artifacts/firmware-controls-browser-report.json").write_text(
        json.dumps({"views": len(reports), "axe": reports, "errors": errors}, indent=2)
    )
    print(
        json.dumps(
            {
                "views": len(reports),
                "axe_violations": sum(len(v) for v in reports.values()),
                "page_errors": errors,
                "controls": "ten-way selection, live edit, force confirmation, soft stop and retained delete verified",
            }
        )
    )
    browser.close()
