"""Exercise device ACL log filters, pagination, details and responsive alignment."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
artifacts = root / "artifacts/blacklist-logs"
artifacts.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1440,"height":1000}, reduced_motion="reduce", bypass_csp=True)
    page.route_web_socket("**/api/v1/ws",lambda ws:None)
    errors, reports = [], {}
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto("http://127.0.0.1:8291/#blacklist-logs")
    page.get_by_label("E-posta",exact=True).fill("browser@example.test")
    page.get_by_label("Parola",exact=True).fill("browser-fixture-password")
    page.get_by_role("button",name="Çalışma alanına gir",exact=True).click()
    expect(page.get_by_role("heading",name="Loglar",exact=True)).to_be_visible()
    expect(page.locator(".acl-log-table tbody tr")).to_have_count(50)
    expect(page.get_by_text("Syslog alıcısı çalışıyor",exact=True)).to_be_visible()

    def check(name):
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
        dialog = page.get_by_role("dialog")
        if dialog.count():
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1"), name
        page.add_script_tag(path=str(root / "frontend/node_modules/axe-core/axe.min.js"))
        reports[name] = page.evaluate("""async()=> (await axe.run(document,{
            runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}
        })).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))""")
        page.screenshot(path=str(artifacts / (name+".png")),full_page=True)

    def sizes(state):
        for width,height in ((1440,1000),(768,1000),(375,812),(740,375)):
            for theme in ("light","dark"):
                page.set_viewport_size({"width":width,"height":height})
                page.evaluate("v=>document.documentElement.dataset.theme=v",theme)
                page.wait_for_timeout(250)
                check(f"{state}-{width}-{height}-{theme}")
        page.set_viewport_size({"width":1440,"height":1000})

    controls = page.locator(".acl-log-filters input,.acl-log-filters select,.acl-log-filters button").evaluate_all(
        "els=>els.map(e=>{const r=e.getBoundingClientRect();return {y:r.y,h:r.height}})")
    assert max(c["y"] for c in controls)-min(c["y"] for c in controls)<=1,controls
    assert max(c["h"] for c in controls)-min(c["h"] for c in controls)<=1,controls
    sizes("populated")
    page.get_by_role("button",name="Sonraki",exact=True).click()
    expect(page.locator(".acl-log-table tbody tr")).to_have_count(15)
    expect(page.get_by_role("button",name="Sonraki",exact=True)).to_be_disabled()
    page.get_by_role("button",name="Önceki",exact=True).click()
    expect(page.locator(".acl-log-table tbody tr")).to_have_count(50)
    page.get_by_role("button",name="Ayrıntı",exact=False).first.click()
    expect(page.get_by_role("dialog")).to_contain_text("192.0.2.200")
    sizes("detail")
    page.keyboard.press("Escape")
    page.get_by_label("ACL loglarında ara",exact=True).fill("not-present")
    expect(page.get_by_text("Bu filtrelerde ACL logu bulunamadı",exact=True)).to_be_visible()
    sizes("empty")
    page.get_by_label("ACL loglarında ara",exact=True).fill("")
    expect(page.locator(".acl-log-table tbody tr")).to_have_count(50)
    select = page.get_by_label("Cihaz",exact=True)
    value = select.locator("option").nth(1).get_attribute("value")
    select.select_option(value)
    expect(page.locator(".acl-log-table tbody tr")).to_have_count(11)
    page.get_by_label("Zaman aralığı",exact=True).select_option("1")
    expect(page.locator(".acl-log-table tbody tr")).to_have_count(10)
    assert not errors and not any(reports.values()), {"errors":errors,"axe":reports}
    print(json.dumps({"views":len(reports),"page_errors":errors,"axe":reports,"filters":True,"pagination":True}))
    browser.close()
