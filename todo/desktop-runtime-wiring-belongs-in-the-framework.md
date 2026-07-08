# Desktop runtime wiring belongs in the framework, not each consumer app

## Context

wesktop's promise is "desktop-class app in a native window (pywebview) or browser, with a dev mode that runs Vite + the ASGI backend together." A consumer app hit a cluster of bugs during ordinary development that are all the same underlying failure: **wesktop delegates runtime wiring — the backend port, the frontend's notion of where the backend is, instance identity, and process lifecycle — to the consumer app, so every consumer re-implements it and gets it wrong.** For a framework that markets a single-command desktop experience, these are embarrassing in a consumer's hands because the consumer did nothing unusual.

Implementation note: wesktop re-exports most of its surface from **fastware** (`wesktop.dev`/`serve`/`config`/... are `from fastware.X import *`). So most root fixes below land in fastware; wesktop-specific items (the native window / `open` lifecycle, single-instance-window behavior) are called out. This is filed as one comprehensive todo because the items share a root cause and a root fix; split into per-item todos at triage if preferred.

## The concrete incident (one session, generic retelling)

A consumer app runs `<app> dev` (Vite + ASGI) and also `<app> open` (native window). Over time: an `open` desktop window from **months earlier** was still running, holding the default backend port, on stale code. A developer started a second `dev` instance on alternate ports. The frontend — served by the new instance — nonetheless talked to the **old** backend, because the frontend's backend URL was a build-time constant pointing at the default port. Result: the new UI listed the old backend's data, new endpoints 404'd against the old backend, and "live" updates from the new backend never reached the window. Every layer behaved "correctly" in isolation; the composition was broken, and no consumer-side code was at fault in a way a consumer could reasonably foresee.

## The bug classes (each with the framework-level fix)

### 1. Frontend↔backend URL is a consumer-owned build-time constant (ROOT CAUSE)
**Symptom:** the frontend learned the backend's location from a committed `VITE_SERVER_URL=http://localhost:<fixed-port>`. It therefore always called that fixed port regardless of which instance actually served it or what port that instance bound. Two instances → the frontend silently phones the wrong one.
**Why it's the framework's job:** wesktop launches *both* the server and the webview (or the dev proxy). It is the only party that knows the *actual* bound port and build identity at runtime. A consumer hand-wiring a URL is guaranteed drift.
**Fix (fastware + wesktop):**
- **Packaged/`open` mode:** load the frontend **same-origin** from the embedded server so REST and WS are, by construction, the server that opened the window. Consumers should write same-origin/relative URLs and never name a port.
- **`dev` mode (the only split):** the dev proxy already fronts Vite; make it also **inject the real backend origin at runtime** (a `window.__WESKTOP__ = { apiBase, wsBase, buildId }` script, or a tiny `/__wesktop/runtime.json` the client fetches on boot) so the consumer never bakes a port into a build. Provide a blessed client helper (`wesktop-client`) that reads it, so consumers stop hand-rolling `import.meta.env` port config.
- Deprecate the "consumer sets `VITE_SERVER_URL`" pattern in docs; if kept as an escape hatch, a runtime value must override it (and that precedence must be documented).

### 2. No single-instance / focus-existing behavior for the native window
**Symptom:** launching again spawns another window/server; nothing detects "already running." A months-old window lingered invisibly, holding a port and serving stale code.
**Fix (wesktop, `open`):** default single-instance for native windows — on second launch, detect the running instance (per-app lock/registry, see #3) and **focus the existing window** instead of spawning a rival. Provide an opt-out for intentional multi-window apps.

### 3. Process lifecycle is unowned: unreliable stop, PID-file clobbering, orphaned children
**Symptom:** `stop` targets a single PID file that later launches overwrite, so it cannot stop *all* instances or the *right* one; a native window's webview/network child processes outlive intent; instances leak.
**Fix (fastware + wesktop):**
- An **instance registry** (not a single PID file): per-instance records (pid, mode, port, build id, started-at, cwd) in a per-app runtime dir.
- `stop`/`stop --all`/`ps`/`doctor` that enumerate and act on the registry, and **reap the whole process group** (granian workers + webview + network processes), not just the parent.
- Register cleanup on window close / signal so `open` never leaves orphans holding a port.

### 4. Dev-mode subprocess port handling is silent and fragile
**Symptom (already patched consumer-side once — should live here):** `dev` forwarded a chosen frontend port to the readiness probe but **not** to the Vite command, so Vite started on its own default; when that default was occupied, Vite silently auto-incremented while the probe waited on the requested port and failed after a fixed timeout. The consumer had to fix this in its own CLI.
**Fix (fastware `dev`):** forward the chosen port to the subprocess **and** forbid silent relocation (`--strictPort` equivalent), so an occupied port is a loud, immediate failure the framework surfaces — never a silent bind-elsewhere. Applies symmetrically to the backend port.

### 5. Dev-mode hides subprocess output and degrades silently on failure
**Symptom:** the Vite subprocess's stdout was discarded; on the readiness timeout the developer saw only "did not start within Ns," never the real cause (it had started — elsewhere).
**Fix (fastware `dev`):** on readiness failure, surface the subprocess's captured stderr/stdout and the actual detected state (e.g. "bound to :NNNN, expected :MMMM"). No silent-degradation, no swallowed output — consistent with the house "hard errors, not warnings" philosophy.

### 6. No backend↔frontend build/version handshake (skew goes undetected)
**Symptom:** a current frontend spoke to a months-old backend; missing endpoints returned 404 and mismatched behavior looked like app bugs.
**Fix (fastware + wesktop):** stamp a build id into both the served frontend and the server; the client sends/handshakes it (header or first WS frame). On mismatch, the framework **refuses or loudly warns** rather than letting a stale backend serve a new frontend. In `open` mode this should be impossible by construction (same build); the handshake protects `dev` and any detached-server setup.

### 7. Readiness/health and "which instance am I" are not first-class
**Symptom:** determining which server had which data, on which port, at which version, required manual `lsof`/`curl` archaeology.
**Fix (fastware + wesktop):** a standard `/__wesktop/health` (port, build id, mode, pid, instance id, active since) mounted for every app, and a `doctor` command that cross-checks the registry (#3) against listening sockets and flags stale/rival/mismatched instances.

## The unifying fix

wesktop should **own the server↔webview↔frontend wiring end-to-end and inject runtime facts** (real port, origin, build id) rather than relying on committed consumer config and single PID files. Same-origin by default in packaged mode; runtime-injected origin in dev mode; a real instance registry with group-aware lifecycle; strict, loud port handling. Every bug above then becomes impossible for a consumer to hit, instead of something each consumer must independently foresee and re-solve.

## Affected (framework side)

fastware: `dev` (port forwarding, strictPort, subprocess output surfacing, runtime-origin injection, readiness/health), `serve`, config/runtime-dir, an instance registry + lifecycle utilities, build-id stamping + handshake middleware. wesktop: `open`/native-window single-instance + focus-existing + child-process reaping, same-origin packaged loading, the `wesktop-client` runtime-config helper, `stop --all`/`ps`/`doctor` CLI surface, docs deprecating consumer-owned backend URLs.

## Effort

L overall; independently shippable in priority order: **#4/#5 (S, dev-mode port + output — highest embarrassment-per-effort)** → **#1 (M, runtime origin injection + client helper — the root cause)** → **#3 (M, instance registry + group-aware stop)** → **#6/#7 (M, build handshake + health/doctor)** → **#2 (M, single-instance window)**.
