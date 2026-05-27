# Headless App Crawl / Diagnose Command

## Context

When a wesktop-served app "isn't working," the root cause is often invisible from the backend: a slow endpoint blocking the single worker, a JS exception, a failed network request, or a broken route. The user sees a blank page and has no diagnostic path.

A `crawl_debug.py` script (attached in this directory along with sample screenshots) was written ad-hoc for ClaudeTimeline to diagnose exactly this situation. It found the root cause in one run: a 5-minute query blocking the single worker, making the entire app appear frozen.

## Proposal

Add a `wesktop diagnose` (or `wesktop crawl`) CLI command that:

1. Launches a headless Playwright browser against the running wesktop app
2. Auto-discovers routes from nav elements, `<a>` tags, and SPA router patterns
3. For each route:
   - Navigates and waits for network idle
   - Captures console messages (log/warn/error)
   - Captures network request failures and slow responses
   - Captures uncaught JS exceptions
   - Takes a screenshot
   - Clicks interactive elements (buttons, links, inputs)
4. Produces a structured report:
   - Per-route status (loaded/broken/slow)
   - All console errors
   - All failed/slow network requests
   - All JS exceptions
   - Performance budget violations
5. Saves screenshots to a directory

## Interface Ideas

```bash
wesktop diagnose                    # Crawl the running app, print report
wesktop diagnose --screenshots ./out/  # Also save screenshots
wesktop diagnose --budget 2s        # Flag any endpoint >2s as slow
wesktop diagnose --json             # Machine-readable output
wesktop diagnose --routes /,/finder,/manage  # Only test specific routes
```

## Integration with wesktop

- Knows the app URL from wesktop's own port management (no manual URL needed)
- Could run automatically as part of `wesktop serve --check` or post-start hook
- Could be wired into CI as a post-deploy smoke test
- The route discovery could leverage wesktop's own route registry if apps expose it

## Dependencies

- `playwright` (optional dep, error message if not installed)
- Playwright chromium browser (`python -m playwright install chromium`)

## Reference Implementation

See `crawl_debug.py` in this directory — the ad-hoc script that diagnosed the ClaudeTimeline issue. It's ~200 lines and covers the core logic. The screenshots in `crawl_screenshots/` show example output.

## Effort

Medium. Core logic exists in the reference script. Main work:
- CLI integration with strictcli
- Route auto-discovery heuristics
- Structured report format
- Making playwright an optional dependency with good error messages
