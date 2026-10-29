"""Accessibility checks against the disposable browser fixture only."""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8201")
assert base.startswith("http://127.0.0.1:"), "Disposable local test target required"
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, bypass_csp=True, reduced_motion="reduce"
    )
    page = context.new_page()
    page.goto(base)
    page.wait_for_load_state("networkidle")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir").click()
    expect(page.locator("main h1")).to_be_visible()
    results = {}
    for key in ("overview", "devices", "discovery", "monitoring", "settings"):
        page.goto(base + "/#" + key)
        page.wait_for_load_state("networkidle")
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        report = page.evaluate(
            "async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
        )
        results[key] = [
            {"id": v["id"], "impact": v["impact"], "nodes": [n["target"] for n in v["nodes"]]}
            for v in report["violations"]
        ]
    Path("artifacts/accessibility.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))
    assert not any(results.values()), "Accessibility violations found"
    browser.close()
