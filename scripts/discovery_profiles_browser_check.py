"""Run against discovery_profiles_fixture on port 8232; never a production URL."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path("artifacts")
root.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page = context.new_page()
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8232/#discovery")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    initial_jobs = context.request.get("http://127.0.0.1:8232/api/v1/jobs").json()["items"]
    page.get_by_role("button", name="Yeni kayıt", exact=True).click()
    dialog = page.get_by_role("dialog")
    institution = dialog.get_by_role("combobox", name="Kurum")
    site = dialog.get_by_role("combobox", name="Lokasyon", exact=True)
    expect(site).to_be_disabled()
    assert dialog.get_by_role("checkbox").count() == 3  # Two SNMP profiles, one enabled flag; no SSH.
    institution.select_option(label="Kuzey Üniversitesi")
    assert site.locator("option").all_text_contents() == ["Lokasyon seçin (isteğe bağlı)", "Kuzey Kampüs"]
    site.select_option(label="Kuzey Kampüs")
    institution.select_option(label="Güney Üniversitesi")
    expect(site).to_have_value("")
    assert site.locator("option").all_text_contents() == ["Lokasyon seçin (isteğe bağlı)", "Güney Kampüs"]
    site.select_option(label="Güney Kampüs")
    dialog.get_by_role("textbox", name="Ad", exact=False).first.fill("Çok profilli kapsam")
    dialog.get_by_role("textbox", name="Ağ (CIDR)").fill("192.0.2.0/30")
    dialog.get_by_role("button", name="Kaydet", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("En az bir SNMP")
    dialog.get_by_role("checkbox", name="Şube SNMP").check()
    dialog.get_by_role("checkbox", name="Merkez SNMP").check()
    assert (
        dialog.locator(".discovery-profile-option")
        .filter(has_text="Şube SNMP")
        .locator(".discovery-profile-order")
        .inner_text()
        == "1"
    )
    reports = {}
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
            dialog.evaluate("el=>el.scrollTop=0")
            assert dialog.evaluate("el=>el.scrollWidth<=el.clientWidth+1")
            # Paired fields and profile rows retain common horizontal edges.
            fields = institution.bounding_box(), site.bounding_box()
            if width > 600:
                assert abs(fields[0]["y"] - fields[1]["y"]) < 1
                assert abs(fields[0]["width"] - fields[1]["width"]) < 1
            options = dialog.locator(".discovery-profile-option").evaluate_all(
                "els=>els.map(e=>{const b=e.getBoundingClientRect();return {x:b.x,w:b.width,h:b.height}})"
            )
            assert all(option["h"] >= 44 for option in options)
            assert (
                len({round(option["x"]) for option in options})
                == len({round(option["w"]) for option in options})
                == 1
            )
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            reports[f"{width}-{theme}"] = violations
            page.screenshot(path=str(root / f"discovery-profiles-{width}-{theme}.png"))
            dialog.evaluate("el=>el.scrollTop=el.scrollHeight")
            footer = dialog.locator(".dialog-footer").bounding_box()
            assert footer["y"] >= 0 and footer["y"] + footer["height"] <= height
            assert footer["x"] >= 0 and footer["x"] + footer["width"] <= width
            assert all(
                button["height"] >= 44
                for button in dialog.locator(".dialog-footer button").evaluate_all(
                    "els=>els.map(el=>({height:el.getBoundingClientRect().height}))"
                )
            )
            page.screenshot(path=str(root / f"discovery-profiles-{width}-{theme}-actions.png"))
    assert not any(reports.values()), reports
    page.set_viewport_size({"width": 1440, "height": 1000})
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/scopes") and response.request.method == "POST"
    ) as saved:
        dialog.get_by_role("button", name="Kaydet", exact=True).click()
    assert saved.value.status == 201, saved.value.text()
    row = saved.value.json()
    assert len(row["credential_ids"]) == 2
    expect(dialog).not_to_be_visible()
    page.get_by_role("row").filter(has_text="Çok profilli kapsam").get_by_role(
        "button", name="Kaydı düzenle", exact=True
    ).click()
    expect(dialog.get_by_role("checkbox", name="Şube SNMP")).to_be_checked()
    expect(dialog.get_by_role("checkbox", name="Merkez SNMP")).to_be_checked()
    expect(institution.locator("option:checked")).to_have_text("Güney Üniversitesi")
    expect(site.locator("option:checked")).to_have_text("Güney Kampüs")
    dialog.get_by_role("checkbox", name="Şube SNMP").uncheck()
    with page.expect_response(
        lambda response: response.request.method == "PUT" and "/api/v1/scopes/" in response.url
    ) as updated:
        dialog.get_by_role("button", name="Kaydet", exact=True).click()
    assert updated.value.status == 200
    assert len(updated.value.json()["credential_ids"]) == 1
    assert context.request.get("http://127.0.0.1:8232/api/v1/jobs").json()["items"] == initial_jobs
    assert not errors, errors
    (root / "discovery-profiles-browser.json").write_text(
        json.dumps({"axe": reports, "errors": errors}, indent=2)
    )
    browser.close()
print(
    "PASS: multi-profile create/edit, institution location filtering, six viewport/theme checks, accessibility and no scan on save"
)
