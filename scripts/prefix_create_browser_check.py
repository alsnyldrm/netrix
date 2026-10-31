"""Time the actual prefix form save against an isolated fixture (no network scans)."""
import json
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors, timings = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8211/#prefixes")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_role("button", name="192.0.2.0/24", exact=True)).to_be_visible()
    Path("artifacts").mkdir(exist_ok=True)
    for width, height, cidr in [(1440,1000,"198.51.100.0/24"),(375,812,"203.0.113.0/24")]:
        page.set_viewport_size({"width":width,"height":height})
        page.get_by_role("button", name="Yeni kayıt", exact=True).click()
        dialog=page.get_by_role("dialog")
        dialog.get_by_label("Ağ bloğu / CIDR",exact=False).fill(cidr)
        dialog.get_by_label("VRF",exact=False).select_option(label="Global")
        dialog.get_by_label("Kurum",exact=False).select_option(label="Fixture Üniversitesi")
        dialog.get_by_label("Lokasyon",exact=False).select_option(label="Kuzey Kampüs")
        assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
        page.screenshot(path=f"artifacts/prefix-create-{width}.png")
        started=time.perf_counter()
        with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith('/api/v1/prefixes')) as response:
            dialog.get_by_role("button",name="Kaydı kaydet",exact=True).click()
        assert response.value.status==201,response.value.text()
        expect(dialog).to_have_count(0)
        expect(page.get_by_role("button",name=cidr,exact=True)).to_be_visible()
        elapsed=round((time.perf_counter()-started)*1000,2)
        assert elapsed<1500,elapsed
        timings.append({"width":width,"save_to_visible_ms":elapsed})
    jobs=page.request.get("http://127.0.0.1:8211/api/v1/jobs").json()["items"]
    assert len([j for j in jobs if j['kind']=='ipam_inventory' and j['status']=='queued'])==2
    assert not errors,errors
    print(json.dumps({"timings":timings,"background_jobs":"queued","errors":errors}))
    browser.close()
