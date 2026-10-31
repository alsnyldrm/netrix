"""Check readable job details at desktop and mobile sizes on an isolated fixture."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path("artifacts")
root.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page = context.new_page()
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8258/#jobs")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    opener = page.get_by_role("button", name="SNMP ağ keşfi · VLAN-60 · 10.6.0.0/21 açıklaması", exact=True)
    expect(opener).to_be_visible()
    opener.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Görev açıklaması")
    expect(dialog.get_by_text("SNMP ağ keşfi", exact=True)).to_be_visible()
    expect(dialog.get_by_text("LLDP/CDP", exact=False)).to_be_visible()
    assert dialog.locator("pre,code,textarea").count() == 0
    reports = {}
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("t=>document.documentElement.dataset.theme=t", theme)
            dialog.evaluate("e=>e.scrollTop=0")
            assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            heading = dialog.locator(".dialog-header h2").bounding_box()
            body = dialog.locator(".job-details-heading h3").bounding_box()
            assert abs(heading["x"] - body["x"]) < 1
            pairs = dialog.locator(".job-timing > div").evaluate_all(
                "es=>es.map(e=>({x:e.getBoundingClientRect().x,w:e.getBoundingClientRect().width}))"
            )
            assert len({round(e["w"]) for e in pairs}) == 1
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            reports[f"{width}-{theme}"] = violations
            page.screenshot(path=str(root / f"task-details-{width}-{theme}.png"))
            close = dialog.get_by_role("button", name="Kapat", exact=True)
            close.scroll_into_view_if_needed()
            bounds = close.bounding_box()
            assert bounds["height"] >= 40 and bounds["x"] + bounds["width"] <= width
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(opener).to_be_focused()
    assert not errors, errors
    assert not any(reports.values()), reports
    print("Task details browser PASS: six layouts, prose, keyboard, alignment, accessibility")
    browser.close()
