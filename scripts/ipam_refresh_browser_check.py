"""Refresh a running scan with real local API calls; no worker or network collectors."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8237"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    collectors, errors = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda r: (
            collectors.append(r.url)
            if r.method == "POST"
            and r.url.endswith(("/discover", "/ping", "/sync"))
            else None
        ),
    )
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    result = page.request.post(
        BASE + "/fixture/scan-result?hostname=ready.example.test", headers={"X-Netrix-Request": "1"}
    ).json()
    job = page.request.get(BASE + "/api/v1/jobs/" + result["job_id"]).json()
    count = page.request.get(BASE + "/api/v1/jobs?limit=100").json()["total"]
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        page.reload()
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
        status = page.locator(".ipam-job")
        expect(status).to_contain_text("Zamanlanmış tarama")
        expect(status).to_contain_text("Kuyruğa alınma:")
        expect(status.locator("time")).to_have_attribute("datetime", job["created_at"])
        page.get_by_title("Açık sayfanın verilerini yenile", exact=True).click()
        page.wait_for_timeout(2300)
        latest = page.request.get(BASE + f"/api/v1/ipam/vlans/{result['vlan_id']}/scan").json()
        assert (latest["id"], latest["created_at"], latest["status"], latest["progress"]) == (
            job["id"],
            job["created_at"],
            "running",
            job["progress"],
        )
        assert page.request.get(BASE + "/api/v1/jobs?limit=100").json()["total"] == count
        assert not collectors, collectors
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            assert not page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))"
            )
            page.screenshot(path=f"/tmp/netrix-refresh-{width}-{theme}.png", full_page=True)
            status.screenshot(path=f"/tmp/netrix-refresh-panel-{width}-{theme}.png")
    # The fixture has no worker. Finish its fake running job before testing the
    # next explicit scan; cancel_requested alone cannot stop an absent worker.
    assert page.request.post(BASE + "/fixture/scan-finish", headers={"X-Netrix-Request": "1"}).ok
    page.reload()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    expect(page.locator(".ipam-job")).to_contain_text("Tamamlandı")
    expect(page.locator(".ipam-job time")).to_have_attribute("datetime", job["created_at"])
    assert page.request.get(BASE + "/api/v1/jobs?limit=100").json()["total"] == count
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/discover")
    ) as pending:
        page.get_by_role("button", name="Tara", exact=True).click()
    assert pending.value.status == 202
    expect(page.locator(".ipam-job")).to_contain_text("Manuel tarama")
    assert len(collectors) == 1 and not errors, (collectors, errors)
    print(
        "PASS: browser reload and toolbar refresh preserve running job ID/time/progress/count, no source POST; explicit Tara works; source/time visible desktop/mobile/landscape, axe"
    )
    browser.close()
