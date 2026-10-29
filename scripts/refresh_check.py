"""Browser regression for background refreshes; all API/WS data is local and fake."""

import asyncio
import json
import os
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright, expect

BASE = os.environ.get("NETRIX_BROWSER_BASE", "http://127.0.0.1:8202")
assert BASE.startswith("http://127.0.0.1:"), "Local test server required"


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.clock.install()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        sockets = []
        await page.route_web_socket("**/api/v1/ws", lambda socket: sockets.append(socket))
        device = {"id": "device-1", "name": "Fixture switch", "management_ip": "192.0.2.1"}
        ports = [{"id": f"port-{i}", "device_id": device["id"], "name": f"Ethernet{i}"} for i in (1, 2)]
        pending = asyncio.Queue()
        release = asyncio.Event()
        delayed = False
        fail = False
        version = 1

        async def api(route):
            url = urlparse(route.request.url)
            query = parse_qs(url.query)
            name = url.path.removeprefix("/api/v1/")
            foreground = (name == "devices" and query.get("limit") == ["25"]) or name == "traffic"
            if delayed and foreground:
                await pending.put(name)
                await release.wait()
            if fail and foreground:
                await route.fulfill(status=503, json={"detail": "Fixture refresh failed"})
                return
            if name == "auth/me":
                data = {"id": "user-1", "display_name": "Refresh tester", "role": "admin"}
            elif name == "dashboard":
                data = {"counts": {}}
            elif name == "traffic":
                data = {
                    "items": []
                    if query.get("hours") == ["1"]
                    else [
                        {
                            "created_at": f"2026-10-29T12:0{i}:00Z",
                            "quality": "valid",
                            "in_bps": version * 1000000,
                            "out_bps": 2000000,
                        }
                        for i in (0, 1)
                    ],
                    "limited": False,
                }
            else:
                rows = {"devices": [dict(device, name=f"Fixture switch {version}")], "interfaces": ports}
                items = [] if query.get("q") else rows.get(name, [])
                data = {"items": items, "total": len(items)}
            await route.fulfill(json=data)

        await page.route("**/api/v1/**", api)
        await page.goto(BASE + "/#devices")
        await page.wait_for_load_state("networkidle")
        await expect(page.locator(".connection-label")).to_have_text("Bağlı")
        await expect(page.locator("tbody")).to_contain_text("Fixture switch 1")

        async def start_refresh(poll=False):
            nonlocal delayed
            delayed = True
            release.clear()
            if poll:
                await page.clock.fast_forward(30000)
            else:
                sockets[-1].send(json.dumps({"type": "refresh"}))
            await asyncio.wait_for(pending.get(), timeout=5)

        async def finish_refresh():
            nonlocal delayed
            async with page.expect_response(
                lambda response: "/traffic?" in response.url or "/devices?limit=25" in response.url
            ):
                release.set()
            await expect(page.locator("main .loading")).to_have_count(0)
            await page.wait_for_load_state("networkidle")
            delayed = False

        # WebSocket and polling must update data without detaching rows or losing focus.
        for poll in (False, True):
            button = page.get_by_role("button", name=f"Fixture switch {version} ayrıntıları")
            await button.focus()
            table = await page.locator("table").element_handle()
            version += 1
            await start_refresh(poll)
            await expect(page.locator("table")).to_be_visible()
            assert await table.evaluate("node => node.isConnected")
            await expect(button).to_be_focused()
            await expect(page.get_by_text("Kayıtlar yükleniyor…", exact=True)).to_have_count(0)
            await finish_refresh()
            await expect(page.locator("tbody")).to_contain_text(f"Fixture switch {version}")

        fail = True
        await start_refresh()
        await finish_refresh()
        await expect(page.get_by_role("alert")).to_contain_text("Fixture refresh failed")
        await expect(page.locator("table")).to_be_visible()
        fail = False
        await start_refresh()
        await finish_refresh()
        await expect(page.get_by_role("alert")).to_have_count(0)

        # Changed filters still show loading; successful empty results stay stable on refresh.
        delayed = True
        release.clear()
        await page.get_by_role("textbox", name="Kayıtlarda ara").fill("no-match")
        await asyncio.wait_for(pending.get(), timeout=5)
        await expect(page.get_by_text("Kayıtlar yükleniyor…", exact=True)).to_be_visible()
        await finish_refresh()
        await start_refresh()
        await expect(page.get_by_text("Kayıtlar yükleniyor…", exact=True)).to_have_count(0)
        await finish_refresh()

        await page.get_by_role("button", name="Trafik gözlemevi", exact=True).click()
        await expect(page.locator(".traffic-chart")).to_be_visible()
        chart = await page.locator(".traffic-chart").element_handle()
        version += 1
        await start_refresh()
        await expect(page.locator(".traffic-chart")).to_be_visible()
        assert await chart.evaluate("node => node.isConnected")
        await finish_refresh()
        await expect(page.locator(".traffic-stats")).to_contain_text(f"{version}.0 Mbps")

        delayed = True
        release.clear()
        await page.locator(".traffic-toolbar select").nth(1).select_option("port-2")
        await asyncio.wait_for(pending.get(), timeout=5)
        await expect(page.get_by_text("Örnekler yükleniyor…", exact=True)).to_be_visible()
        await finish_refresh()
        await page.locator(".traffic-toolbar select").nth(2).select_option("1")
        await expect(page.get_by_text("Henüz trafik gözlemi yok.", exact=True)).to_be_visible()
        await start_refresh()
        await expect(page.get_by_text("Henüz trafik gözlemi yok.", exact=True)).to_be_visible()
        await expect(page.get_by_text("Örnekler yükleniyor…", exact=True)).to_have_count(0)
        await finish_refresh()
        assert not errors, errors
        print(
            json.dumps(
                {
                    "background_refresh": "PASS",
                    "websocket": True,
                    "polling": True,
                    "focus_preserved": True,
                    "filters": True,
                    "empty_states": True,
                    "error_recovery": True,
                    "traffic": True,
                    "console_errors": errors,
                }
            )
        )
        await browser.close()


asyncio.run(check())
