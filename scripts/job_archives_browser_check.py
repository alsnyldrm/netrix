"""Exercise task ZIP actions in the isolated task_center_fixture (no network jobs)."""

import json
from pathlib import Path
from zipfile import ZipFile

from playwright.sync_api import expect, sync_playwright

root = Path("artifacts")
root.mkdir(exist_ok=True)
base = "http://127.0.0.1:8258"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    page = context.new_page()
    page.route_web_socket("**/api/v1/ws", lambda socket: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/#jobs")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Tümünü arşive gönder", exact=True)).to_be_visible()
    for width, height in ((1440, 1000), (375, 812)):
        page.set_viewport_size({"width": width, "height": height})
        button = page.get_by_role("button", name="Tümünü arşive gönder", exact=True)
        expect(button).to_be_visible()
        bounds = button.bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(root / f"task-archive-button-{width}.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    original = context.request.get(base + "/api/v1/jobs").json()
    finished = [j for j in original["items"] if j["status"] not in ("queued", "running")]
    assert finished
    page.get_by_role("button", name="Tümünü arşive gönder", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="görev ZIP arşivine taşındı")).to_be_visible()
    expect(page.locator("tbody tr")).to_have_count(original["total"] - len(finished))
    page.screenshot(path=str(root / "task-archive-button-1440.png"), full_page=True)
    page.goto(base + "/#job-archives")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Görev Arşivi", exact=True)).to_be_visible()
    table = page.get_by_role("region", name="Görev ZIP kayıtları", exact=True)
    expect(table.locator("tbody tr")).to_have_count(1)
    link = table.locator(".archive-download").first
    with page.expect_download() as download_event:
        link.click()
    download = download_event.value
    assert download.suggested_filename.endswith(".zip")
    with ZipFile(download.path()) as archive:
        assert len(json.loads(archive.read("gorevler.json"))["jobs"]) == len(finished)
    reports = {}
    for width, height in ((1440, 1000), (375, 812), (812, 375)):
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("dark", "light"):
            page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if width == 1440:
                title = page.locator(".job-archives-panel .table-title").bounding_box()
                button = page.get_by_role("button", name="Seçilenleri sil", exact=True).bounding_box()
                assert abs(title["y"] + title["height"] / 2 - button["y"] - button["height"] / 2) < 1
                cells = table.locator("thead th").evaluate_all("es=>es.map(e=>e.getBoundingClientRect().x)")
                body = (
                    table.locator("tbody tr")
                    .first.locator("td")
                    .evaluate_all("es=>es.map(e=>e.getBoundingClientRect().x)")
                )
                assert all(abs(a - b) < 1 for a, b in zip(cells, body))
            page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
            violations = page.evaluate(
                "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))"
            )
            reports[f"{width}-{theme}"] = violations
            page.screenshot(path=str(root / f"task-archives-{width}-{theme}.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    # Cancel a single deletion, then select all and delete the ZIP.
    table.get_by_role("button", name=" sil", exact=False).first.click()
    dialog = page.get_by_role("dialog", name="Görev arşivlerini sil", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Vazgeç", exact=True).click()
    expect(table.locator("tbody tr")).to_have_count(1)
    page.get_by_label("Bu sayfadaki tüm arşivleri seç", exact=True).check()
    page.get_by_role("button", name="Seçilenleri sil (1)", exact=True).click()
    expect(dialog).to_be_visible()
    for width in (1440, 375):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
        assert dialog.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
        page.screenshot(path=str(root / f"task-archives-delete-{width}.png"), full_page=True)
    dialog.get_by_role("button", name="Arşivleri sil", exact=True).click()
    expect(page.get_by_role("heading", name="Henüz görev arşivi yok", exact=True)).to_be_visible()
    assert not errors, errors
    assert not any(reports.values()), reports
    print(
        "Task archives browser PASS: archive all, ZIP download, selection, cancel/delete, six layouts, alignment, Axe A/AA"
    )
    browser.close()
