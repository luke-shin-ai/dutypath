"""Open the demo over http and watch the engine build the graph in the tab.

The static page check (``scripts/check_demo.py``) opens the page from the file
system, where a worker and the wasm fetch are blocked.  This check serves the
repository over http, opens the published path ``docs/demo/``, and waits for
the panel's own report:

* the worker starts, builds the graph and names the counts it created,
* every value the engine returns for the shipment on screen equals the value
  the committed bundle was built from (the parity line says how many agree),
* the picture of each market's path is drawn from that engine's rows, and the
  three verdicts it shows for the shipment as declared equal the bundle's,
* the key material toggle sends the new line to the engine, the three verdicts
  and the three duties move together, and what the page computes equals the
  engine's own answer for that second state (the bundle's ``toggle`` report),
* a second shipment gives the same agreement, and a shipment with no second
  state leaves the toggle disabled,
* neither viewport scrolls sideways and the visible text stays free of the
  characters that give machine written text away.

    python scripts/check_wasm_demo.py
"""

from __future__ import annotations

import functools
import http.server
import json
import mimetypes
import os
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "demo"
SHOTS = DEMO / "screenshots"
FORBIDDEN = ["\u2014", "\u2013", "\u00b7", "\u2192", "\u2026", "\u201c", "\u201d", "\u2018", "\u2019"]
VIEWPORTS = [
    {"name": "desktop-1440", "width": 1440, "height": 940},
    {"name": "mobile-390", "width": 390, "height": 844},
]


def _ensure_chromium_libs() -> None:
    import ctypes.util

    if ctypes.util.find_library("nspr4"):
        return
    for base in (ROOT, *ROOT.parents):
        for candidate in (
            base / ".sysroot" / "usr" / "lib" / "x86_64-linux-gnu",
            base / ".sysroot" / "lib" / "x86_64-linux-gnu",
        ):
            if (candidate / "libnspr4.so").exists():
                current = os.environ.get("LD_LIBRARY_PATH", "")
                os.environ["LD_LIBRARY_PATH"] = str(candidate) + (":" + current if current else "")
                return


def serve(directory: Path):
    mimetypes.add_type("application/wasm", ".wasm")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def read_state(page):
    return page.evaluate(
        """() => ({
            status: document.getElementById('engine-status').textContent,
            parity: document.getElementById('engine-parity').textContent,
            rows: document.querySelectorAll('#engine-body tbody tr').length,
            readout: document.getElementById('graph-readout').textContent,
            readoutClass: document.getElementById('graph-readout').className,
            figures: document.querySelectorAll('#graph-host .graph-figure').length,
            drawings: document.querySelectorAll('#graph-host svg').length,
            verdicts: [...document.querySelectorAll('#graph-host .graph-figure svg')]
                .map(svg => svg.getAttribute('aria-label')),
            toggleDisabled: document.getElementById('material-toggle').disabled,
            toggleChecked: document.getElementById('material-toggle').checked,
            text: document.body.innerText,
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
        })"""
    )


def main() -> int:
    _ensure_chromium_libs()
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    bundle = json.loads((DEMO / "dutypath-demo.json").read_text(encoding="utf-8"))
    toggle_case = next(case for case in bundle["cases"] if case.get("toggle"))
    filed = {block["market"]: (block["origin"]["verdict"], block["duty"]["amount"])
             for block in toggle_case["report"]["markets"]}
    swapped = {block["market"]: (block["origin"]["verdict"], block["duty"]["amount"])
               for block in toggle_case["toggle"]["report"]["markets"]}

    server, port = serve(ROOT)
    url = "http://127.0.0.1:%d/docs/demo/" % port
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for viewport in VIEWPORTS:
                page = browser.new_page(viewport={"width": viewport["width"], "height": viewport["height"]})
                page.goto(url)
                page.wait_for_selector(".market")
                page.wait_for_function(
                    "() => document.getElementById('engine-parity').textContent.indexOf('agree') >= 0",
                    timeout=180000,
                )
                page.wait_for_function(
                    "() => document.querySelectorAll('#graph-host svg').length === 3",
                    timeout=120000,
                )
                page.wait_for_timeout(200)
                state = read_state(page)
                shot = SHOTS / ("wasm-%s.png" % viewport["name"])
                page.screenshot(path=str(shot), full_page=True)
                found = sorted({char for char in FORBIDDEN if char in state["text"]})
                filed_verdicts = [item.split(": ", 1)[1] for item in state["verdicts"]]
                expected_filed = [filed[market][0] for market in ("US", "EU", "JP")]

                page.click("#material-toggle")
                page.wait_for_function(
                    "() => document.getElementById('graph-readout').textContent.indexOf('NOT ORIGINATING') >= 0",
                    timeout=120000,
                )
                page.wait_for_timeout(200)
                moved = read_state(page)
                swapped_shot = SHOTS / ("wasm-%s-swapped.png" % viewport["name"])
                page.screenshot(path=str(swapped_shot), full_page=True)
                moved_found = sorted({char for char in FORBIDDEN if char in moved["text"]})
                swapped_verdicts = [item.split(": ", 1)[1] for item in moved["verdicts"]]
                expected_swapped = [swapped[market][0] for market in ("US", "EU", "JP")]

                results.append(
                    {
                        "viewport": viewport["name"],
                        "status": state["status"],
                        "parity": state["parity"],
                        "engine_rows": state["rows"],
                        "horizontal_scroll_px": state["scrollWidth"] - state["clientWidth"],
                        "forbidden_characters": found,
                        "drawings": state["drawings"],
                        "filed_verdicts": filed_verdicts,
                        "expected_filed_verdicts": expected_filed,
                        "toggle_disabled": state["toggleDisabled"],
                        "readout_filed": state["readout"],
                        "screenshot": str(shot.relative_to(ROOT)),
                        "after_toggle": {
                            "readout": moved["readout"],
                            "readout_class": moved["readoutClass"],
                            "verdicts": swapped_verdicts,
                            "expected_verdicts": expected_swapped,
                            "horizontal_scroll_px": moved["scrollWidth"] - moved["clientWidth"],
                            "forbidden_characters": moved_found,
                            "toggle_checked": moved["toggleChecked"],
                            "screenshot": str(swapped_shot.relative_to(ROOT)),
                        },
                    }
                )
                page.close()

            # A second shipment, chosen the way a reader would choose it, and one
            # that has no second state of its key material.
            page = browser.new_page(viewport={"width": 1440, "height": 940})
            page.goto(url)
            page.wait_for_function(
                "() => document.getElementById('engine-parity').textContent.indexOf('agree') >= 0",
                timeout=180000,
            )
            options = page.eval_on_selector_all("#case option", "els => els.map(e => e.value + ' ' + e.textContent)")
            target = None
            for option in options:
                if " SHP-2026-1201-001" in option:
                    target = option.split(" ", 1)[0]
                    break
            if target is None:
                target = "0"
            before = page.inner_text("#engine-parity")
            page.select_option("#case", target)
            page.wait_for_function(
                "(before) => document.getElementById('engine-parity').textContent !== before && " +
                "document.getElementById('engine-parity').textContent.indexOf('agree') >= 0",
                arg=before,
                timeout=180000,
            )
            page.wait_for_timeout(400)
            second = read_state(page)
            shot = DEMO / "screenshots" / "wasm-second-shipment.png"
            page.screenshot(path=str(shot), full_page=True)
            results.append(
                {
                    "viewport": "second shipment",
                    "case": page.eval_on_selector("#case", "el => el.selectedOptions[0].textContent"),
                    "parity": second["parity"],
                    "status": second["status"],
                    "verdicts": second["verdicts"],
                    "drawings": second["drawings"],
                    "toggle_disabled": second["toggleDisabled"],
                    "screenshot": str(shot.relative_to(ROOT)),
                }
            )
            page.close()
            browser.close()
    finally:
        server.shutdown()

    print(json.dumps({"url": url, "results": results}, indent=2, ensure_ascii=False))
    failed = []
    for entry in results:
        if entry.get("viewport") == "second shipment":
            if entry["drawings"] != 3 or not entry["toggle_disabled"]:
                failed.append(entry)
            continue
        after = entry["after_toggle"]
        if (
            entry.get("forbidden_characters")
            or entry.get("horizontal_scroll_px", 0) != 0
            or " values agree" not in entry.get("parity", "")
            or entry.get("engine_rows", 3) != 3
            or entry.get("drawings") != 3
            or entry.get("filed_verdicts") != entry.get("expected_filed_verdicts")
            or entry.get("toggle_disabled")
            or after["forbidden_characters"]
            or after["horizontal_scroll_px"] != 0
            or not after["toggle_checked"]
            or after["verdicts"] != after["expected_verdicts"]
            or "3 of 3 verdicts and 3 of 3 duties agree" not in after["readout"]
        ):
            failed.append(entry)
    if failed:
        print(json.dumps({"failed": failed}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
