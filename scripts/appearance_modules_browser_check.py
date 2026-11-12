"""Read-only module flows in the Lumelle layout, with responsive navigation regressions."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
out = Path("artifacts/appearance-modules")
out.mkdir(parents=True, exist_ok=True)
reports = {}
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    for palette in ("cobalt", "amber"):
        response = context.request.put(
            BASE + "/api/v1/access/preferences",
            data={"palette": palette},
            headers={"X-Netrix-Request": "1"},
        )
        assert response.ok, response.text()
        page.reload()
        page.wait_for_load_state("networkidle")
        for route in ["vlans", "configuration", "topology", "firmware-images", "users"]:
            page.goto(BASE + "/#" + route)
            page.wait_for_load_state("networkidle")
            expect(page.locator("html")).to_have_attribute("data-design", "lumelle")
            for width in [1440, 375]:
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
                page.evaluate("()=>document.documentElement.dataset.theme='dark'")
                page.wait_for_function(
                    """()=> {const s=getComputedStyle(document.documentElement);const h=s.getPropertyValue('--text').trim().slice(1);const rgb=`rgb(${[0,2,4].map(i=>parseInt(h.slice(i,i+2),16)).join(', ')})`;return s.color===rgb;}"""
                )
                # ResizeObserver in the topology canvas updates after the viewport event.
                page.wait_for_function("() => document.body.scrollWidth <= innerWidth", timeout=5000)
                page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
                key = f"{route}-{palette}-{width}"
                reports[key] = page.evaluate(
                    "async()=>(await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
                )
                page.screenshot(path=str(out / (key + ".png")))
        page.get_by_role("button", name="Menüyü aç", exact=True).click()
        sidebar = page.get_by_role("complementary", name="Ana menü")
        envanter = sidebar.get_by_role("button", name="Envanter", exact=True)
        if envanter.get_attribute("aria-expanded") == "false":
            envanter.click()
        sidebar.get_by_role("button", name="Cihaz envanteri", exact=True).click()
        expect(page).to_have_url(BASE + "/#devices")
        expect(sidebar).to_be_hidden()
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Menüyü daralt", exact=True).click()
        buttons = page.locator(".sidebar-user-actions button").evaluate_all(
            "es=>es.map(e=>{const r=e.getBoundingClientRect(),p=e.closest('.sidebar').getBoundingClientRect();return {left:r.left,right:r.right,asideLeft:p.left,asideRight:p.right};})"
        )
        assert all(b["left"] >= b["asideLeft"] and b["right"] <= b["asideRight"] for b in buttons), buttons
        page.get_by_role("button", name="Menüyü genişlet", exact=True).click()
    browser.close()
violations = {k: v for k, v in reports.items() if v}
(out / "report.json").write_text(
    json.dumps({"checks": len(reports), "violations": violations, "errors": errors}, indent=2)
)
assert not violations, violations
assert not errors, errors
print(json.dumps({"checks": len(reports), "violations": 0, "errors": 0}))
