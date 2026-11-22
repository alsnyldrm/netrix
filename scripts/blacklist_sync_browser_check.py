"""Browser checks for the blacklist sync workspace (run against scripts/blacklist_sync_fixture.py on :8291)."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "blacklist-sync"
OUT.mkdir(parents=True, exist_ok=True)
reports, errors, align = {}, [], {}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", bypass_csp=True)
    page.route_web_socket("**/api/v1/ws", lambda ws: None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8291/#blacklist")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    expect(page.get_by_text("198.51.100.10", exact=True)).to_be_visible()

    def check(name):
        assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth"), name
        dlg = page.get_by_role("dialog")
        if dlg.count():
            assert dlg.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), name
        page.add_script_tag(path=str(ROOT / "frontend/node_modules/axe-core/axe.min.js"))
        v = page.evaluate("""async () => (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target).slice(0,4)}))""")
        reports[name] = v
        # row action vertical alignment: all buttons in a row-actions share a center line
        align[name] = page.evaluate("""() => [...document.querySelectorAll('.blacklist-row-actions')].slice(0,6).map(g => {
            const c=[...g.children].filter(x=>x.offsetParent).map(x=>{const r=x.getBoundingClientRect();return Math.round((r.top+r.bottom)/2)});
            return c.length? Math.max(...c)-Math.min(...c) : 0 }).filter(d=>d>1)""")
        page.screenshot(path=str(OUT / (name + ".png")), full_page=True)

    def sizes(label):
        for w in (1440, 768, 375):
            for theme in ("light", "dark"):
                page.set_viewport_size({"width": w, "height": 1000})
                page.emulate_media(color_scheme=theme)
                page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                page.wait_for_timeout(450)
                check(f"{label}-{w}-{theme}")

    sizes("entries")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_label("198.51.100.10 kaydını seç").check()
    page.get_by_label("198.51.100.11 kaydını seç").check()
    expect(page.get_by_text("2 kayıt seçildi")).to_be_visible()
    sizes("selection")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("region", name="Seçim işlemleri").get_by_role("button", name="Sil").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    sizes("bulk-delete")
    page.get_by_role("button", name="Vazgeç").click()
    page.get_by_role("button", name="198.51.100.10 ayrıntısı").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    sizes("detail")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Toplu ekle").click()
    page.get_by_role("dialog").get_by_role("textbox").first.fill("192.0.2.200\n192.0.2.201, 198.51.100.10")
    sizes("bulk-add")
    page.get_by_role("dialog").get_by_text("Kampüs çekirdek").click()
    page.get_by_role("button", name="Kayıtları ekle").click()
    expect(page.get_by_text("2 IP kaydı eklendi. Zaten kayıtlı 1 adres atlandı.")).to_be_visible()
    page.get_by_label("IP kaydı ara").fill("192.0.2.20")
    expect(page.get_by_text("2 / 8 IP kaydı")).to_be_visible()
    page.get_by_label("IP kaydı ara").fill("")
    page.get_by_role("button", name="198.51.100.12 kaydını sil").click()
    page.get_by_role("button", name="Kaldır ve sil").click()
    expect(page.get_by_text("198.51.100.12", exact=True)).to_have_count(0)

    page.goto("http://127.0.0.1:8291/#blacklist-groups")
    expect(page.get_by_text("Kampüs çekirdek", exact=True)).to_be_visible()
    sizes("groups")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="Uzak binalar grubunu sil").click()
    sizes("group-delete")
    page.get_by_role("button", name="Vazgeç").click()

    page.goto("http://127.0.0.1:8291/#blacklist-devices")
    expect(page.get_by_text("Fixture 6100", exact=True)).to_be_visible()
    sizes("devices")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="Fixture 6100 son eşitleme işi").click()
    sizes("device-job")
    browser.close()
bad = {k: v for k, v in reports.items() if v}
print(json.dumps({"views": len(reports), "axe": bad, "misaligned": {k: v for k, v in align.items() if v}, "errors": errors}, ensure_ascii=False, indent=1))
