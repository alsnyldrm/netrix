"""Real local API and browser pages: batch dock, safe tab handoff and saved commands."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8241"
OUT = Path("artifacts/bulk-workspace")
OUT.mkdir(parents=True, exist_ok=True)
errors, reports, posts, cancels = [], {}, [], []
hold = False
fail_next_result = False
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True
    )
    context.route_web_socket("**/api/v1/ws", lambda ws: None)

    def results(route):
        global fail_next_result
        if fail_next_result:
            fail_next_result = False
            route.fulfill(status=503, json={"detail": "Geçici sonuç bağlantı hatası"})
            return
        response = route.fetch()
        value = response.json()
        if hold and response.ok:
            value["status"] = "running"
            for index, target in enumerate(value["targets"]):
                target.update(status="running" if index == 0 else "queued", output="")
        route.fulfill(response=response, json=value)

    context.route(
        "**/api/v1/access/batches/*",
        lambda route: results(route) if route.request.method == "GET" else route.continue_(),
    )

    def attached(page):
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda r: (
                posts.append(r.post_data_json)
                if r.method == "POST" and r.url.endswith("/api/v1/access/batches")
                else cancels.append(r.url)
                if r.method == "DELETE" and "/api/v1/access/batches/" in r.url
                else None
            ),
        )
        page.set_default_timeout(10000)

    page = context.new_page()
    attached(page)
    page.goto(BASE + "/#devices")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.wait_for_load_state("networkidle")

    def request(path, method="GET", data=None):
        r = context.request.fetch(
            BASE + "/api/v1" + path, method=method, data=data, headers={"X-Netrix-Request": "1"}
        )
        assert r.ok, (r.status, r.text())
        return r.json() if r.status != 204 else None

    request(
        "/access/commands",
        "PUT",
        {
            "items": [
                {"id": "c1", "name": "Conf", "command": "show version"},
                {"id": "c2", "name": "running conf", "command": "show running-config"},
            ]
        },
    )
    devices = request("/access/devices")["items"][:2]

    def open_batch():
        page.evaluate(
            "devices=>window.dispatchEvent(new CustomEvent('netrix:ssh-batch',{detail:devices}))", devices
        )
        return page.get_by_role("dialog", name="Toplu komut gönder", exact=True)

    batch = open_batch()
    batch.get_by_role("button", name="Conf komutunu seç", exact=True).click()
    expect(batch.get_by_label("Gönderilecek komut", exact=True)).to_have_value("show version")
    assert not posts
    # Shared library editing remains available, without executing commands.
    batch.get_by_role("button", name="Conf komutunu düzenle", exact=True).click()
    batch.get_by_label("Komut adı", exact=True).fill("Version")
    batch.get_by_role("button", name="Değişiklikleri kaydet", exact=True).click()
    expect(batch.get_by_role("button", name="Version komutunu seç", exact=True)).to_be_visible()
    batch.get_by_role("button", name="Toplu komutu tam ekran yap", exact=True).click()
    expect(batch).to_have_class("ssh-dialog ssh-batch-dialog ssh-full")
    batch.get_by_role("button", name="Toplu komut penceresini küçült", exact=True).click()
    batch.get_by_role("button", name="Toplu komutu simge durumuna küçült", exact=True).click()
    page.get_by_role("button", name="Toplu komut penceresini aç", exact=True).click()
    expect(batch.get_by_label("Gönderilecek komut", exact=True)).to_have_value("show version")
    assert not posts and not cancels
    # A draft tab contains encrypted server input; no SSH work has been queued.
    with page.expect_popup() as popup_info:
        batch.get_by_role("button", name="Toplu komutu yeni sekmede aç", exact=True).click()
    draft = popup_info.value
    attached(draft)
    draft.wait_for_url("**/batch/draft/*")
    draft.wait_for_load_state("networkidle")
    draft_batch = draft.get_by_role("dialog", name="Toplu komut gönder", exact=True)
    expect(draft_batch.get_by_label("Gönderilecek komut", exact=True)).to_have_value("show version")
    assert "show" not in draft.url and not posts and not cancels
    expect(page.locator(".ssh-batch-dialog")).to_have_count(0)
    hold = True
    fail_next_result = True
    draft_batch.get_by_role("button", name="Komutu gönder", exact=True).click()
    expect(draft_batch.get_by_role("alert")).to_contain_text("Geçici sonuç bağlantı hatası")
    draft_batch.get_by_role("button", name="Sonucu yenile", exact=True).click()
    draft.wait_for_url("**/batch/*")
    expect(draft_batch.locator(".ssh-header > .ssh-state")).to_have_text("Çalışıyor")
    assert "/draft/" not in draft.url and len(posts) == 1
    saved_id = draft.url.rsplit("/", 1)[1]
    draft_batch.get_by_role("button", name="Toplu komutu simge durumuna küçült", exact=True).click()
    draft.wait_for_timeout(1700)
    assert not cancels
    draft.get_by_role("button", name="Toplu komut penceresini aç", exact=True).click()
    expect(draft_batch).to_be_visible()
    hold = False
    expect(draft_batch.locator(".ssh-header > .ssh-state")).to_have_text("Tamamlandı")
    draft_batch.locator(".batch-results nav button").nth(1).click()
    expect(draft_batch.locator(".batch-results pre")).to_contain_text("authentication failed")
    # Refresh restores the existing result, never re-posting the command.
    draft.reload()
    expect(
        draft.get_by_role("dialog", name="Toplu komut gönder", exact=True).locator(".batch-summary")
    ).to_contain_text("1 başarılı")
    assert len(posts) == 1 and saved_id in draft.url
    draft.close()
    # Active job handoff keeps its original ID and does not cancel on source unmount.
    batch = open_batch()
    batch.get_by_role("button", name="Version komutunu seç", exact=True).click()
    hold = True
    batch.get_by_label("Cihaz başına süre (saniye)", exact=True).fill("45")
    batch.get_by_role("button", name="Komutu gönder", exact=True).click()
    expect(batch.locator(".ssh-header > .ssh-state")).to_have_text("Çalışıyor")
    assert len(posts) == 2
    with page.expect_popup() as popup_info:
        batch.get_by_role("button", name="Toplu komutu yeni sekmede aç", exact=True).click()
    live = popup_info.value
    attached(live)
    live.wait_for_url("**/batch/*")
    live_batch = live.get_by_role("dialog", name="Toplu komut gönder", exact=True)
    expect(live_batch.locator(".ssh-header > .ssh-state")).to_have_text("Çalışıyor")
    assert len(posts) == 2 and not cancels
    expect(live_batch.get_by_label("Cihaz başına süre (saniye)", exact=True)).to_have_value("45")
    hold = False
    expect(live_batch.locator(".ssh-header > .ssh-state")).to_have_text("Tamamlandı")
    live_batch.get_by_role("button", name="Yeni komut hazırla", exact=True).click()
    expect(live_batch.get_by_role("button", name="Version komutunu seç", exact=True)).to_be_enabled()
    live_batch.get_by_role("button", name="Toplu komut penceresini kapat", exact=True).click()
    live.close()
    # A blocked popup preserves the draft and never sends a network command.
    batch = open_batch()
    page.evaluate("()=>{window.originalOpen=window.open;window.open=()=>null}")
    batch.get_by_role("button", name="Toplu komutu yeni sekmede aç", exact=True).click()
    expect(batch.get_by_role("alert")).to_contain_text("engelledi")
    assert len(posts) == 2
    page.evaluate("()=>window.open=window.originalOpen")
    batch.get_by_role("button", name="Toplu komut penceresini kapat", exact=True).click()
    # Explicit close cancels an active job once; minimize and handoff above did not.
    batch = open_batch()
    batch.get_by_role("button", name="Version komutunu seç", exact=True).click()
    hold = True
    batch.get_by_role("button", name="Komutu gönder", exact=True).click()
    expect(batch.locator(".ssh-header > .ssh-state")).to_have_text("Çalışıyor")
    batch.get_by_role("button", name="Toplu komut penceresini kapat", exact=True).click()
    page.wait_for_timeout(250)
    assert len(cancels) == 1 and len(posts) == 3
    hold = False
    batch = open_batch()

    def capture(key):
        assert batch.evaluate("e=>e.scrollWidth<=e.clientWidth"), key
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), key
        assert batch.locator(".ssh-footer").evaluate("e=>e.getBoundingClientRect().bottom<=innerHeight+1"), (
            key
        )
        tools = batch.locator(".ssh-window-actions button").evaluate_all(
            "es=>es.map(e=>({x:e.getBoundingClientRect().left,y:e.getBoundingClientRect().top,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))"
        )
        assert len({round(e["y"]) for e in tools}) == 1 and len({e["h"] for e in tools}) == 1, (key, tools)
        page.add_script_tag(path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve()))
        reports[key] = page.evaluate(
            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))"
        )
        page.screenshot(path=str(OUT / f"{key}.png"))
        (OUT / "partial.json").write_text(json.dumps(reports, indent=2))

    for design in ("atlas", "orbit", "terminal", "panorama", "focus"):
        for mode in ("dark", "light"):
            page.evaluate(
                "v=>{document.documentElement.dataset.design=v.design;document.documentElement.dataset.theme=v.mode;document.documentElement.dataset.palette='amber'}",
                {"design": design, "mode": mode},
            )
            for width in (1440, 375):
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 812})
                page.wait_for_timeout(650)
                capture(f"{design}-{mode}-{width}")
    page.set_viewport_size({"width": 812, "height": 375})
    capture("landscape")
    failures = {k: v for k, v in reports.items() if v}
    (OUT / "report.json").write_text(
        json.dumps(
            {
                "screens": len(reports),
                "violations": failures,
                "errors": errors,
                "batch_posts": len(posts),
                "explicit_cancellations": len(cancels),
            },
            indent=2,
        )
    )
    assert not failures, failures
    assert not errors, errors
    browser.close()
print(json.dumps({"screens": len(reports), "violations": {}, "errors": errors, "batch_posts": len(posts)}))
