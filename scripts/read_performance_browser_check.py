"""Regression for refresh storms, instant details, fresh writes and screen navigation."""

import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path

from playwright.async_api import async_playwright, expect

BASE = "http://127.0.0.1:8215"
MEASURE_ONLY = os.environ.get("NETRIX_MEASURE_ONLY") == "1"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
        sockets, requests, errors = [], [], []
        await page.route_web_socket("**/api/v1/ws", lambda ws: sockets.append(ws))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request", lambda r: requests.append(r.url.split("/api/v1")[-1]) if "/api/v1/" in r.url else None
        )

        async def slow_table(route):
            await asyncio.sleep(0.8)
            await route.continue_()

        async def slow_detail(route):
            await asyncio.sleep(1.2)
            await route.continue_()

        await page.route("**/api/v1/ipam/vlans/*/addresses?*", slow_table)
        await page.route("**/api/v1/ipam/addresses/*", slow_detail)
        await page.goto(BASE + "/#vlans")
        await page.get_by_label("E-posta", exact=True).fill("browser@example.test")
        await page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
        await page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
        await page.get_by_role("button", name="192.0.2.0/24", exact=True).wait_for()
        await page.wait_for_load_state("networkidle")
        initial_requests = len(requests)
        requests.clear()

        async def burst():
            for _ in range(35):
                for socket in sockets:
                    socket.send(json.dumps({"type": "refresh"}))
                await asyncio.sleep(0.1)

        started = time.perf_counter()
        task = asyncio.create_task(burst())
        await page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
        await page.get_by_role("button", name="192.0.2.10", exact=True).wait_for(timeout=15000)
        first_rows_ms = round((time.perf_counter() - started) * 1000)
        await task
        await page.wait_for_timeout(1200)
        report = {
            "initial_requests": initial_requests,
            "first_rows_ms": first_rows_ms,
            "burst_requests": len(requests),
            "requests": dict(Counter(x.split("?")[0] for x in requests)),
        }
        print(json.dumps(report), flush=True)
        if MEASURE_ONLY:
            await browser.close()
            return
        assert first_rows_ms < 2500, report
        assert len(requests) <= 10, report
        assert not any(
            x.startswith(("/devices?", "/interfaces?", "/links?", "/credentials?")) for x in requests
        )

        await page.get_by_role("button", name="192.0.2.10", exact=True).click()
        dialog = page.get_by_role("dialog")
        await expect(dialog.get_by_text("FBU-DS", exact=True)).to_be_visible(timeout=500)
        await expect(dialog.get_by_text("89", exact=True)).to_be_visible()
        await expect(dialog.get_by_role("status")).to_have_text("Kaynak gözlemleri yükleniyor…")
        await expect(dialog.get_by_role("status")).to_have_count(0, timeout=5000)
        await expect(dialog.get_by_text("VMware vCenter", exact=True)).to_be_visible()

        async def check_layout(name):
            for width, height in ((1440, 1000), (375, 812)):
                await page.set_viewport_size({"width": width, "height": height})
                await page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert await page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth"), name
                for modal in await page.get_by_role("dialog").all():
                    assert await modal.evaluate("e=>e.scrollWidth<=e.clientWidth"), name
                await page.add_script_tag(
                    path=str(Path("frontend/node_modules/axe-core/axe.min.js").resolve())
                )
                violations = await page.evaluate(
                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map(v=>v.id)"
                )
                assert not violations, (name, violations)
                await page.screenshot(path=f"/tmp/netrix-performance-{name}-{width}.png", full_page=True)
            await page.set_viewport_size({"width": 1440, "height": 1000})

        await check_layout("detail")
        await page.get_by_role("button", name="Pencereyi kapat", exact=True).click()
        await page.get_by_role("button", name="Yalnızca aktif IP’ler", exact=True).click()
        await expect(page.get_by_role("row")).to_have_count(2)
        await check_layout("addresses")
        search = page.get_by_placeholder("Tüm alanlarda ara…")
        await search.fill("missing-host")
        await expect(page.get_by_text("Gösterilecek kayıt yok.")).to_be_visible()
        await search.fill("app-01")
        await page.get_by_role("button", name="192.0.2.10", exact=True).wait_for()

        # An unrelated catalog mutation must be visible immediately on return.
        await page.evaluate("location.hash='operating-systems'")
        await page.get_by_role("button", name="Yeni kayıt", exact=True).click()
        await page.get_by_role("textbox", name="İşletim sistemi", exact=True).fill("Performance OS")
        await page.get_by_role("button", name="Kaydı kaydet", exact=True).click()
        await page.get_by_role("cell", name="Performance OS", exact=True).wait_for()

        for key in [
            "devices",
            "archived-devices",
            "interfaces",
            "device-types",
            "configuration",
            "backup-changes",
            "backup-compare",
            "backup-settings",
            "backup-groups",
            "topology",
            "neighbors",
            "deleted-links",
            "discovery",
            "jobs",
            "events",
            "cabinets",
            "sites",
            "operating-systems",
            "dns-servers",
            "vrfs",
            "integrations",
            "overview",
            "alerts",
            "rules",
            "credentials",
            "audit",
            "users",
            "settings",
        ]:
            await page.evaluate("key=>location.hash=key", key)
            await page.wait_for_timeout(100)
            await page.wait_for_load_state("networkidle")
            await expect(page.locator("main")).not_to_contain_text("Kayıtlar yükleniyor…", timeout=5000)
            assert not await page.locator(".page-error").count(), (
                key,
                await page.locator("main").inner_text(),
            )
        await page.evaluate("location.hash='vlans'")
        await page.get_by_role("button", name="192.0.2.0/24", exact=True).wait_for()
        await check_layout("vlans")
        assert not errors, errors
        await browser.close()
        print(
            "PASS: bounded refresh requests; details, search, active filter, saved data, 28 screens, desktop/mobile and accessibility"
        )


asyncio.run(main())
