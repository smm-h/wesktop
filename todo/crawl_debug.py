"""
Playwright-based headless crawl of the ClaudeTimeline SPA.

FINDING: The server runs granian with 1 worker. The /api/executables endpoint
takes ~278 seconds. Once triggered (by the Finder page), the single worker is
blocked and NO other requests can be served. This causes the app to appear
completely frozen.

Strategy: Load the page ONCE, wait for it to fully settle (including the slow
executables call), then gather all diagnostics from that single loaded page.
Navigate between routes using in-page pushState (no full reloads).
"""

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

sys.stdout.reconfigure(line_buffering=True)

BASE_URL = "http://127.0.0.1:8000"
SCREENSHOT_DIR = Path("/home/m/Projects/ClaudeTimeline/crawl_screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Collectors
console_messages = []
network_failures = []
page_errors = []
request_log = []
all_responses = []


def setup_listeners(page):
    def on_console(msg):
        console_messages.append({
            "type": msg.type,
            "text": msg.text,
            "location": f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}",
        })

    def on_pageerror(error):
        page_errors.append({"message": str(error)})

    def on_requestfailed(request):
        network_failures.append({
            "url": request.url,
            "method": request.method,
            "failure": request.failure,
        })

    def on_response(response):
        all_responses.append({
            "url": response.url,
            "status": response.status,
            "method": response.request.method,
        })
        if response.status >= 400:
            request_log.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
            })

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("requestfailed", on_requestfailed)
    page.on("response", on_response)


def screenshot(page, name):
    path = SCREENSHOT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False, timeout=5000)
    except Exception as e:
        print(f"  [SCREENSHOT FAILED] {name}: {str(e)[:60]}")


def spa_navigate(page, path):
    """Navigate within the SPA using the router's push() function."""
    try:
        page.evaluate(f"""() => {{
            // The SPA router uses a custom 'urlchange' event
            window.history.pushState({{}}, '', '{path}');
            // Trigger the router's sync
            window.dispatchEvent(new PopStateEvent('popstate'));
            window.dispatchEvent(new Event('urlchange'));
        }}""")
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PwTimeout:
            pass
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  [SPA NAV ERROR] {str(e)[:100]}")


def main():
    print("=" * 70)
    print("  ClaudeTimeline Headless Crawl - Diagnostic Report")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()
        setup_listeners(page)

        # === PHASE 1: Load the app and wait for EVERYTHING ===
        print("\n[PHASE 1] Initial page load")
        print("  Loading /finder (will wait up to 300s for all API calls)...")
        t0 = time.time()

        try:
            page.goto(BASE_URL + "/finder", wait_until="commit", timeout=10000)
        except PwTimeout:
            print("  [WARN] commit timeout")

        # Wait for the app to fully load including the slow executables API
        # The key insight: networkidle won't fire until ALL fetches complete
        print("  Waiting for network idle (may take minutes due to slow API calls)...")
        try:
            page.wait_for_load_state("networkidle", timeout=300000)
            elapsed = time.time() - t0
            print(f"  Network idle reached after {elapsed:.1f}s")
        except PwTimeout:
            elapsed = time.time() - t0
            print(f"  [WARN] Network idle timeout after {elapsed:.1f}s (some requests may still be pending)")

        screenshot(page, "01_initial_loaded")
        print(f"  URL: {page.url}")
        print(f"  Responses received: {len(all_responses)}")

        # Show what loaded
        api_calls = [r for r in all_responses if '/api/' in r['url']]
        asset_calls = [r for r in all_responses if '/assets/' in r['url']]
        print(f"  API calls: {len(api_calls)}, Asset loads: {len(asset_calls)}")
        for r in api_calls:
            print(f"    {r['status']} {r['url'][len(BASE_URL):]}")

        body = page.evaluate("() => document.body?.textContent?.length || 0")
        print(f"  Body text: {body} chars")

        dom = page.evaluate("""() => {
            const nav = document.querySelector('nav.top-nav');
            const main = document.querySelector('.route-outlet');
            const inputs = document.querySelectorAll('input').length;
            const buttons = document.querySelectorAll('button').length;
            const svgs = document.querySelectorAll('svg').length;
            const h2s = Array.from(document.querySelectorAll('h2,h3')).map(h=>h.textContent.trim()).filter(t=>t&&t.length<60);
            return {navText: nav?.textContent?.trim()?.substring(0,100), mainLen: main?.textContent?.length, inputs, buttons, svgs, h2s: h2s.slice(0,10)};
        }""")
        print(f"  DOM: main={dom['mainLen']}ch inputs={dom['inputs']} btns={dom['buttons']} svgs={dom['svgs']}")
        if dom['h2s']:
            print(f"  Headers: {dom['h2s']}")

        # === PHASE 2: Navigate routes via SPA router ===
        print("\n\n[PHASE 2] Navigate routes via SPA router")
        routes = [
            ("finder", "/finder"),
            ("bookmarks", "/bookmarks"),
            ("dashboard", "/dashboard"),
            ("timeline", "/timeline"),
            ("manage", "/manage"),
            ("semantic_map", "/semantic-map"),
            ("console_page", "/console"),
        ]

        for name, path in routes:
            print(f"\n  --- {name} ({path}) ---")
            pre_e = len(page_errors)
            pre_f = len(network_failures)
            pre_h = len(request_log)

            spa_navigate(page, path)
            screenshot(page, f"02_{name}")

            try:
                info = page.evaluate("""() => {
                    const main = document.querySelector('.route-outlet');
                    const text = main?.textContent?.trim() || '';
                    const svgs = document.querySelectorAll('svg').length;
                    const h2s = Array.from(document.querySelectorAll('h2,h3'))
                        .map(h=>h.textContent.trim()).filter(t=>t&&t.length<60);
                    const inputs = document.querySelectorAll('input').length;
                    const btns = Array.from(document.querySelectorAll('button'))
                        .filter(b => b.offsetParent)
                        .map(b => b.textContent.trim())
                        .filter(t => t && t.length < 40 && !['Search','Ctrl+K',''].includes(t.trim()));
                    return {textLen: text.length, preview: text.substring(0,200), svgs, h2s: h2s.slice(0,15), inputs, btns: btns.slice(0,15)};
                }""")
                print(f"  Content: {info['textLen']} chars | SVGs: {info['svgs']} | Inputs: {info['inputs']}")
                if info['h2s']:
                    print(f"  Headers: {info['h2s']}")
                if info['btns']:
                    print(f"  Buttons: {info['btns'][:10]}")
                if info['textLen'] < 50:
                    print(f"  [WARN] Very little content!")
                    print(f"  Preview: '{info['preview']}'")
            except Exception as e:
                print(f"  [EVALUATE ERROR] {str(e)[:100]}")

            ne = page_errors[pre_e:]
            nf = network_failures[pre_f:]
            nh = request_log[pre_h:]
            if ne:
                print(f"  ** JS EXCEPTIONS ({len(ne)}):")
                for err in ne:
                    print(f"    {err['message'][:200]}")
            if nf:
                print(f"  ** NETWORK FAILURES ({len(nf)}):")
                for f in nf:
                    print(f"    {f['method']} {f['url']} -> {f['failure']}")
            if nh:
                print(f"  ** HTTP ERRORS ({len(nh)}):")
                for h in nh:
                    print(f"    {h['method']} {h['url']} -> {h['status']}")
            if not ne and not nf and not nh:
                print("  [OK] No errors")

        # === PHASE 3: Finder interactions ===
        print("\n\n[PHASE 3] Finder interactions")
        spa_navigate(page, "/finder")

        inputs_info = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input'))
                .map((el,i) => ({i, type:el.type, placeholder:el.placeholder, vis:el.offsetParent!==null}));
        }""")
        print(f"  Inputs ({len(inputs_info)}):")
        for inp in inputs_info:
            if inp['vis']:
                print(f"    [{inp['i']}] type={inp['type']} placeholder='{inp['placeholder']}'")

        # Search
        search = page.query_selector('input[placeholder*="Search messages"]')
        if search:
            print("\n  Searching for 'docker'...")
            pre_e = len(page_errors)
            pre_h = len(request_log)
            search.fill("docker")
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PwTimeout:
                pass
            ne = page_errors[pre_e:]
            nh = request_log[pre_h:]
            if ne:
                print(f"  [JS ERROR] {ne[0]['message'][:150]}")
            elif nh:
                print(f"  [HTTP ERROR] {nh[0]['status']} {nh[0]['url']}")
            else:
                result = page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href*="/session/"]').length;
                    const main = document.querySelector('.route-outlet');
                    const text = main?.textContent || '';
                    return {links, textLen: text.length, preview: text.substring(0,150)};
                }""")
                print(f"  [OK] {result['textLen']} chars, {result['links']} session links")
                print(f"  Preview: {result['preview'][:100]}")
            screenshot(page, "03_finder_docker")

        # Date range buttons
        print("\n  Date range buttons:")
        for btn_text in ["Today", "7d", "30d", "All"]:
            pre_e = len(page_errors)
            pre_h = len(request_log)
            try:
                page.click(f"button:text-is('{btn_text}')", timeout=3000)
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except PwTimeout:
                    pass
                ne = page_errors[pre_e:]
                nh = request_log[pre_h:]
                if ne or nh:
                    issues = []
                    if ne:
                        issues.append(f"{len(ne)} JS")
                    if nh:
                        issues.append(f"{len(nh)} HTTP")
                    print(f"  '{btn_text}' -> {', '.join(issues)} errors")
                    for e in ne[:1]:
                        print(f"    {e['message'][:100]}")
                    for h in nh[:1]:
                        print(f"    {h['status']} {h['url']}")
                else:
                    print(f"  '{btn_text}' -> [OK]")
            except Exception as e:
                print(f"  '{btn_text}' -> FAILED: {str(e)[:60]}")

        # === PHASE 4: Dashboard ===
        print("\n\n[PHASE 4] Dashboard")
        spa_navigate(page, "/dashboard")
        page.wait_for_timeout(5000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PwTimeout:
            pass

        try:
            dash = page.evaluate("""() => {
                const h2s = Array.from(document.querySelectorAll('h2,h3'))
                    .map(h=>h.textContent.trim()).filter(t=>t&&t.length<60);
                const svgs = document.querySelectorAll('svg').length;
                const details = Array.from(document.querySelectorAll('details'))
                    .map(d => ({summary: d.querySelector('summary')?.textContent?.trim()?.substring(0,40), open: d.open}));
                const btns = Array.from(document.querySelectorAll('button'))
                    .filter(b => b.offsetParent && !['Search','Ctrl+K',''].includes(b.textContent.trim()) && b.textContent.trim().length < 40)
                    .map(b => b.textContent.trim());
                return {h2s, svgs, details: details.slice(0,10), btns: btns.slice(0,15)};
            }""")
            print(f"  SVGs: {dash['svgs']}")
            print(f"  Headers: {dash['h2s']}")
            print(f"  Details: {dash['details']}")
            print(f"  Buttons: {dash['btns']}")
        except Exception as e:
            print(f"  [ERROR] {str(e)[:100]}")
        screenshot(page, "03_dashboard")

        # === PHASE 5: Command palette ===
        print("\n\n[PHASE 5] Command palette")
        pre_e = len(page_errors)
        page.keyboard.press("Control+k")
        page.wait_for_timeout(1000)
        try:
            palette = page.evaluate("""() => {
                const els = document.querySelectorAll('dialog[open], [role="dialog"], [class*="palette"], [class*="cmdk"]');
                const visible = Array.from(els).filter(el => el.open || el.offsetParent !== null || getComputedStyle(el).display !== 'none');
                const inputs = Array.from(document.querySelectorAll('input'))
                    .filter(el => el.offsetParent !== null)
                    .map(el => ({type: el.type, placeholder: el.placeholder}));
                return {count: visible.length, tags: visible.map(v=>v.tagName), inputs};
            }""")
            print(f"  Palette elements: {palette['count']} ({palette['tags']})")
            print(f"  Visible inputs: {palette['inputs']}")
        except Exception as e:
            print(f"  [ERROR] {str(e)[:80]}")
        screenshot(page, "04_palette")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        ne = page_errors[pre_e:]
        if ne:
            print(f"  Errors: {[e['message'][:60] for e in ne]}")
        else:
            print("  [OK]")

        # === PHASE 6: Theme toggle ===
        print("\n\n[PHASE 6] Theme toggle")
        theme_btn = page.query_selector("button.theme-toggle")
        if theme_btn:
            pre_e = len(page_errors)
            theme_btn.click()
            page.wait_for_timeout(300)
            theme_btn.click()
            page.wait_for_timeout(300)
            theme_btn.click()
            page.wait_for_timeout(300)
            ne = page_errors[pre_e:]
            print(f"  {'ERROR: ' + ne[0]['message'][:100] if ne else '[OK] Cycled 3x without errors'}")

        # === PHASE 7: API scan (using page.request which bypasses the page) ===
        print("\n\n[PHASE 7] API endpoint scan")
        api_endpoints = [
            "/api/stats",
            "/api/projects",
            "/api/executables",
            "/api/accounts",
            "/api/timeline",
            "/api/search?q=test",
            "/api/sessions",
            "/api/clusters",
            "/api/embeddings",
            "/api/narrative",
            "/api/failures",
            "/api/branches",
            "/api/top-ngrams",
            "/api/session-shape",
            "/api/outliers",
            "/api/tokens",
            "/api/tools",
            "/api/finder?q=test",
            "/api/manage/info",
            "/api/similar?message_id=1",
            "/api/errors?q=error",
            "/api/rhythm",
            "/api/annotations",
            "/api/pasted-content",
            "/api/dangerous",
            "/api/subagents",
            "/api/executables/lifecycle",
            "/api/project-lifecycle",
            "/api/assistant",
            "/api/health",
        ]
        ok_count = 0
        fail_count = 0
        slow_endpoints = []
        for endpoint in api_endpoints:
            t0 = time.time()
            try:
                resp = page.request.get(BASE_URL + endpoint, timeout=30000)
                elapsed = time.time() - t0
                status = resp.status
                if status < 400:
                    ok_count += 1
                    if elapsed > 2.0:
                        slow_endpoints.append((endpoint, elapsed, status))
                        print(f"  [SLOW {elapsed:.1f}s] {endpoint} -> {status}")
                else:
                    fail_count += 1
                    body = resp.text()[:200]
                    print(f"  [FAIL {status}] {endpoint}")
                    print(f"           {body}")
            except Exception as e:
                fail_count += 1
                elapsed = time.time() - t0
                print(f"  [TIMEOUT/ERROR {elapsed:.1f}s] {endpoint}: {str(e)[:60]}")

        print(f"\n  API: {ok_count} OK, {fail_count} failed / {len(api_endpoints)} total")
        if slow_endpoints:
            print(f"  Slow endpoints (>2s):")
            for ep, t, s in sorted(slow_endpoints, key=lambda x: -x[1]):
                print(f"    {t:.1f}s: {ep}")

        # === PHASE 8: Session detail ===
        print("\n\n[PHASE 8] Session detail")
        spa_navigate(page, "/finder")
        search = page.query_selector('input[placeholder*="Search messages"]')
        if search:
            search.fill("git commit")
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PwTimeout:
                pass

            session_links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href*="/session/"]'))
                    .slice(0, 5)
                    .map(a => ({href: a.getAttribute('href'), text: a.textContent.trim().substring(0,50)}));
            }""")
            print(f"  Session links: {len(session_links)}")
            for sl in session_links[:3]:
                print(f"    {sl['href']}: '{sl['text']}'")

            if session_links:
                href = session_links[0]['href']
                print(f"  Navigating to {href}...")
                pre_e = len(page_errors)
                spa_navigate(page, href)
                page.wait_for_timeout(3000)
                ne = page_errors[pre_e:]
                if ne:
                    print(f"  [JS ERROR] {ne[0]['message'][:150]}")
                else:
                    det = page.evaluate("""() => {
                        return document.querySelector('.route-outlet')?.textContent?.length || 0;
                    }""")
                    print(f"  [OK] {det} chars rendered")
                screenshot(page, "03_session_detail")

        # === PHASE 9: localStorage ===
        print("\n\n[PHASE 9] localStorage")
        try:
            ls = page.evaluate("""() => {
                const items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    items[k] = localStorage.getItem(k).substring(0, 200);
                }
                return items;
            }""")
            if ls:
                for k, v in ls.items():
                    print(f"  {k}: {v[:100]}")
            else:
                print("  (empty)")
        except Exception as e:
            print(f"  ERROR: {str(e)[:100]}")

        ctx.close()
        browser.close()

    # =============== FINAL SUMMARY ===============
    print("\n\n")
    print("=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)

    errors_only = [m for m in console_messages if m["type"] == "error"]
    warnings_only = [m for m in console_messages if m["type"] == "warning"]

    print(f"\n  Total console messages:   {len(console_messages)}")
    print(f"  Console ERRORS:           {len(errors_only)}")
    print(f"  Console WARNINGS:         {len(warnings_only)}")
    print(f"  Network failures:         {len(network_failures)}")
    print(f"  HTTP 4xx/5xx responses:   {len(request_log)}")
    print(f"  Uncaught JS exceptions:   {len(page_errors)}")
    print(f"  Total responses seen:     {len(all_responses)}")

    if page_errors:
        print(f"\n  {'='*60}")
        print(f"  UNCAUGHT JS EXCEPTIONS ({len(page_errors)})")
        print(f"  {'='*60}")
        seen = set()
        for err in page_errors:
            short = err['message'][:200]
            if short not in seen:
                seen.add(short)
                count = sum(1 for e in page_errors if e['message'][:200] == short)
                suffix = f" (x{count})" if count > 1 else ""
                print(f"\n  {err['message'][:600]}{suffix}")

    if errors_only:
        print(f"\n  {'='*60}")
        print(f"  CONSOLE ERRORS ({len(errors_only)})")
        print(f"  {'='*60}")
        seen = set()
        for msg in errors_only:
            short = msg['text'][:150]
            if short not in seen:
                seen.add(short)
                count = sum(1 for m in errors_only if m['text'][:150] == short)
                suffix = f" (x{count})" if count > 1 else ""
                print(f"\n  {msg['text'][:500]}{suffix}")
                if msg['location'] and msg['location'] != ':':
                    print(f"    at {msg['location']}")

    if warnings_only:
        print(f"\n  {'='*60}")
        print(f"  CONSOLE WARNINGS ({len(warnings_only)})")
        print(f"  {'='*60}")
        seen = set()
        for msg in warnings_only:
            short = msg['text'][:150]
            if short not in seen:
                seen.add(short)
                count = sum(1 for m in warnings_only if m['text'][:150] == short)
                suffix = f" (x{count})" if count > 1 else ""
                print(f"\n  {msg['text'][:400]}{suffix}")

    if network_failures:
        print(f"\n  {'='*60}")
        print(f"  NETWORK FAILURES ({len(network_failures)})")
        print(f"  {'='*60}")
        for f in network_failures:
            print(f"\n  {f['method']} {f['url']}")
            print(f"    Failure: {f['failure']}")

    if request_log:
        print(f"\n  {'='*60}")
        print(f"  HTTP ERROR RESPONSES ({len(request_log)})")
        print(f"  {'='*60}")
        seen = set()
        for r in request_log:
            key = f"{r['method']} {r['url']} {r['status']}"
            if key not in seen:
                seen.add(key)
                count = sum(1 for x in request_log if f"{x['method']} {x['url']} {x['status']}" == key)
                suffix = f" (x{count})" if count > 1 else ""
                print(f"  {r['method']} {r['url']} -> {r['status']}{suffix}")

    # Full console log
    if console_messages:
        print(f"\n  {'='*60}")
        print(f"  FULL CONSOLE LOG ({len(console_messages)} entries)")
        print(f"  {'='*60}")
        for msg in console_messages:
            print(f"  [{msg['type'].upper():7}] {msg['text'][:300]}")

    print(f"\n\n  Screenshots saved to: {SCREENSHOT_DIR}/")
    print("  Done.")


if __name__ == "__main__":
    main()
