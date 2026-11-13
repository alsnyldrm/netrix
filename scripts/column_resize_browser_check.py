"""Run against ipam_manual_fixture: real pointer resizing, persistence and layout."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NETRIX_BROWSER_URL", "http://127.0.0.1:8224")
OUT = Path(os.environ.get("NETRIX_RESIZE_ARTIFACTS", "/tmp/netrix-resize-live"))
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("NETRIX_CHROMIUM"), headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page.route_web_socket("**/api/v1/ws", lambda _: None)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/#vlans")
    page.get_by_label("E-posta", exact=True).fill("browser@example.test")
    page.get_by_label("Parola", exact=True).fill("browser-fixture-password")
    page.get_by_role("button", name="Çalışma alanına gir", exact=True).click()
    page.get_by_role("button", name="192.0.2.0/24", exact=True).click()
    table = page.locator(".ipam-address-table")
    head = table.get_by_role("columnheader", name="Hostname", exact=True)
    expect(table.get_by_role("button", name="192.0.2.11", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")

    def frame():
        page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def width(el):
        return el.evaluate("el => el.getBoundingClientRect().width")

    def same(actual, expected):
        assert abs(actual - expected) < 1.6, (actual, expected)

    def settled(header, expected):
        page.wait_for_function(
            "({element, expected}) => Math.abs(element.getBoundingClientRect().width - expected) < 1.6",
            arg={"element": header.element_handle(), "expected": expected},
            timeout=1500,
        )
        same(width(header), expected)

    def widths():
        return table.locator("thead th").evaluate_all(
            "es => Object.fromEntries(es.map(e => [e.dataset.columnWidthKey,e.getBoundingClientRect().width]))"
        )

    def saved():
        return page.evaluate("localStorage.getItem('netrix-column-width:ipam-addresses')")

    def begin(grip):
        grip.click(trial=True)
        r = grip.evaluate("el => el.getBoundingClientRect().toJSON()")
        x, y = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
        if not grip.evaluate("(el,p) => el === document.elementFromPoint(...p)", [x, y]):
            page.screenshot(path=OUT / "blocked-handle.png")
            raise AssertionError(
                page.evaluate("p => ({point:p, hit:document.elementFromPoint(...p)?.outerHTML})", [x, y])
            )
        page.mouse.move(x, y)
        page.mouse.down()
        return x, y

    def drag(header, delta, grip=None):
        grip = grip if grip is not None else header.locator(".column-table-resize-right")
        before, stored = width(header), saved()
        x, y = begin(grip)
        for fraction in (0.25, 0.5, 0.75, 1):
            page.mouse.move(x + delta * fraction, y, steps=2)
            frame()
            same(width(header), max(96, min(1600, before + delta * fraction)))
        assert saved() == stored, "Do not save transient drag widths"
        live = width(header)
        page.mouse.up()
        frame()
        settled(header, live)
        assert not page.locator("html").evaluate("el => el.classList.contains('column-resizing')")
        return live

    initial = width(head)
    original = widths()
    drag(head, 90)
    # Adjacent columns retain their widths, not a share of the resized width.
    for key, value in widths().items():
        if key != "named:hostname":
            same(value, original[key])
    drag(head, -45)
    # The same boundary from inside the next sticky header has identical behavior.
    next_head = head.locator("xpath=following-sibling::th[1]")
    next_width = width(next_head)
    drag(head, 40, next_head.locator(".column-table-resize-left"))
    same(width(next_head), next_width)
    drag(head, -30, next_head.locator(".column-table-resize-left"))

    # Reversing at the minimum has no dead zone, even after overshooting it.
    x, y = begin(head.locator(".column-table-resize-right"))
    page.mouse.move(x - 400, y, steps=3)
    frame()
    same(width(head), 96)
    page.mouse.move(x - 360, y, steps=3)
    frame()
    same(width(head), 136)
    page.mouse.up()
    frame()

    # Drag out of the header and release; pointer capture must keep ownership.
    before = width(head)
    x, y = begin(head.locator(".column-table-resize-right"))
    page.mouse.move(x + 70, y + 180, steps=5)
    frame()
    same(width(head), before + 70)
    page.mouse.up()
    frame()
    same(width(head), before + 70)

    for cancellation in ("escape", "pointercancel", "blur"):
        before, stored = width(head), saved()
        grip = head.locator(".column-table-resize-right")
        x, y = begin(grip)
        page.mouse.move(x + 80, y, steps=3)
        frame()
        same(width(head), before + 80)
        if cancellation == "escape":
            page.keyboard.press("Escape")
        elif cancellation == "blur":
            page.evaluate("window.dispatchEvent(new Event('blur'))")
        else:
            grip.dispatch_event("pointercancel", {"pointerId": 1})
        page.mouse.up()
        frame()
        settled(head, before)
        assert saved() == stored
        assert page.locator("html.column-resizing").count() == 0

    head.locator(".column-table-resize-right").dblclick()
    frame()
    settled(head, initial)
    fitted = width(head)
    drag(head, 80)
    next_head.locator(".column-table-resize-left").dblclick()
    frame()
    settled(head, fitted)
    drag(head, 35)
    expected = width(head)
    page.reload()
    expect(table.get_by_role("button", name="192.0.2.11", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")
    frame()
    settled(head, expected)

    # Reload old very narrow stored widths, then recover by dragging/autofit.
    page.evaluate(
        "localStorage.setItem('netrix-column-width:ipam-addresses', JSON.stringify({'named:hostname':96,'named:address':96,'named:scan_status':96}))"
    )
    page.reload()
    expect(table.get_by_role("button", name="192.0.2.11", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")
    frame()
    header_height = head.bounding_box()["height"]
    assert head.locator(".column-table-label").evaluate("el => getComputedStyle(el).whiteSpace") == "nowrap"
    drag(head, 95)
    assert head.bounding_box()["height"] <= header_height + 1

    for size in ((1440, 1000), (375, 812)):
        page.set_viewport_size(dict(zip(("width", "height"), size)))
        for theme in ("light", "dark"):
            page.evaluate("v => document.documentElement.dataset.theme=v", theme)
            drag(head, 30)
            drag(head, -30)
            head.locator(".column-table-resize-right").dblclick()
            frame()
            button = head.get_by_role("button", name="Hostname sütununu taşı", exact=True)
            button.focus()
            page.keyboard.press("Enter")
            menu = page.get_by_role("group", name="Hostname sütun sırası", exact=True)
            expect(menu).to_be_visible()
            w = width(head)
            menu.get_by_role("button", name="Genişlet", exact=True).click()
            frame()
            settled(head, w + 24)
            menu.get_by_role("button", name="Daralt", exact=True).click()
            frame()
            settled(head, w)
            page.keyboard.press("Escape")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if size[0] < 760:
                table.locator("tbody").scroll_into_view_if_needed()
            page.screenshot(path=OUT / f"columns-{size[0]}-{theme}.png")

    page.set_viewport_size({"width": 1440, "height": 1000})
    # Reordering does not change which column owns each shared boundary.
    head.get_by_role("button", name="Hostname sütununu taşı", exact=True).click()
    page.get_by_role("group", name="Hostname sütun sırası", exact=True).get_by_role(
        "button", name="Sağa taşı", exact=True
    ).click()
    frame()
    drag(head, 25)
    assert head.locator("xpath=preceding-sibling::th[1]").get_attribute("data-column-id") == "mac_address"
    row = table.get_by_role("row").filter(has=page.get_by_role("button", name="192.0.2.11", exact=True))
    same(width(row.locator('[data-column-id="hostname"]')), width(head))
    expect(row.locator('[data-column-id="hostname"]')).to_contain_text("MANUAL-FW-11")

    # A second module: actual inventory table, sorting and drag isolation.
    page.goto(BASE + "/#devices")
    inventory = page.locator(".device-inventory-table")
    first = inventory.locator("th[data-column-id]").first
    expect(first).to_be_visible()
    frame()
    drag(first, 65)
    drag(first, -40)
    first.get_by_role("button", name="sırala", exact=False).click()
    assert first.get_attribute("aria-sort") in ("ascending", "descending")
    assert not errors, errors
    browser.close()
    print(
        "PASS: live widths before release, both boundary sides, reversal at minimum, pointer capture/cancel, autofit, stored widths, reorder, keyboard, inventory sorting and desktop/mobile themes"
    )
