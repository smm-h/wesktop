# Migration Plan: codehome + ClaudeTimeline to wesktop

Covers every wesktop feature to build, every migration step, and every resolved decision. Both migrations run in parallel. wesktop gains shared infrastructure; app-specific logic stays in each consumer.

---

## Resolved decisions

### What goes into wesktop (reusable)

| Feature | Detail |
|---|---|
| Dependency injection | Per-request resolution, async support, generator cleanup, caching. DI for HTTP and WebSocket handlers. |
| Auth module | JWT (HS256, PyJWT), bcrypt passwords, session cookies, CSRF double-submit. 3 token sources: Bearer header, session cookie, query param. Opt-in. |
| Rate limiting | Decorator-based on individual handlers. No middleware (SSE-safe). In-memory token bucket. |
| SDUI | 39 Pydantic UI primitives. Provider registry. Server-driven UI trees. |
| Feature flags | Define flags with defaults. Override from JSON. API: enabled(), all_flags(), set_override(), reload(). |
| Audit logging | Append-only JSONL writer. App-defined events. Configurable path. Async-safe. |
| Background tasks | Registry with start()/stop() protocol. Feature-gated. Lifecycle tied to serve() lifespan. |
| Observability | Request ID (UUID4, structlog binding, response header), request timing (status, duration, ring buffer), slow-request buffer. |
| Error tracking | Optional Sentry integration (DSN in config, request context, user context). |
| Error log | SQLite-backed 5xx error log. Timestamps, detail, context. Ties into timing middleware. |
| structlog | wesktop configures structlog: JSON in prod, colored console in dev. Auto-detect via isatty(). |
| CORS middleware | Opt-in via create_app(cors_origins=[...]). Preflight OPTIONS handling. |
| TrustedHost middleware | Blocks DNS rebinding for localhost servers. Configurable allowed hosts. |
| Dev proxy | Vite HMR proxy. Proxies non-API requests to Vite dev server. WebSocket passthrough for HMR. |
| TestClient | from wesktop.testing import TestClient. Wraps httpx + ASGITransport. Sync and async. |
| Exception handler registry | app.exception_handler(ExcType, handler_fn). Checked before generic 500. |
| response_model | Route decorator validates outgoing responses via Pydantic. Validation errors become 500. |
| Request body parsing | req.json_as(Model) for Pydantic validation. 422 on failure with field errors. |
| Query validation | req.query("limit", type_=int, ge=0, le=100). 422 on constraint violation. |
| query_list(name) | Returns all values for a multi-value query key. query() stays single-value. |
| Path param coercion | {id:int} syntax. 400 on type mismatch. {param:str} as explicit default. |
| Body reading | All HTTP methods, not just POST. |
| Error format | {"detail": "..."} matching FastAPI convention. Both frontends already expect this. |
| WebSocket path params | {session_id} in WS routes. Same matching as HTTP. |
| WebSocket helper class | accept(), close(), send_json(), send_bytes(), receive_json(), receive_bytes(). Path params, headers, query. |
| PUT/PATCH decorators | @router.put(path), @router.patch(path). |
| Router composition | include_router(router, prefix="/api/v1") for prefix mounting. Router-level dependencies for blanket auth. |
| HTTPError exception | Raise from handlers with status_code and detail. Caught by app. HTTPError(status, detail) uses positional args (not keyword like FastAPI's HTTPException(status_code=X, detail=Y)). |
| Server stop/status | stop(pid_path): SIGTERM, wait, SIGKILL. status(pid_path, health_url): liveness + health. |
| serve(foreground) | Single function, foreground is required (no default). False spawns daemon thread. |
| Pre-serve callback | serve(pre_serve=fn). Called before Granian starts. |
| Env var settings | App-namespaced: {NAME}_HOST, {NAME}_PORT. Explicit args override. No implicit defaults for host/port. |
| Reload | Conditional on Granian benchmark. watchfiles + Granian restart if cold start < 500ms. |
| Config via strictcli | Apps register config schema. strictcli provides show/set/edit/path subcommands. |
| Pydantic | Direct dependency for validation. |
| App state | ASGI lifespan state. Lifespan yields dict, wesktop merges into scope["state"] per request. Request.state property for access. |
| Response cookies/headers | All response types gain optional headers dict and cookies list. set_cookie() helper produces Set-Cookie header strings. Replaces FastAPI's mutable Response injection. |
| Cookie extraction | req.cookies property (parsed dict), req.cookie(name) method. |
| {key:path} converter | Greedy path matching for multi-segment params. Must be last in route pattern. |
| FileResponse | Serves files from disk with Content-Length, MIME detection, chunked reading. |
| ASGI helpers | send_error(send, status, detail) for middleware error responses. Canonical ASGI type aliases (Scope, Receive, Send). |
| Serialization boundary | Pydantic for schema validation (model_validate/model_dump). msgspec for wire encoding (JSON bytes). These do not conflict: Pydantic produces dicts, msgspec encodes them. |

### What stays in each app

| Feature | Owner | Detail |
|---|---|---|
| Plugin system | codehome | Manifest-driven (TOML), discovery, dependency sorting, namespace mounting, dynamic CLI commands via argparse. |
| Event bus | codehome | FILTER + DONE transports, 50+ event types, subscribers (SSE forwarder, audit). |
| EventManager (SSE) | codehome | Keeps its own SSE class. Uses wesktop StreamResponse for HTTP only. |
| State stores | codehome | Scoped (branch/repo/project/global), atomic JSON, file locking. |
| Check framework | codehome | Groups, dependency sorting, concurrent async, timeouts, advisory flags. |
| Docker management | codehome | Compose start/stop/inspect via Docker SDK. |
| Operation progress | codehome | OperationTracker for 202 Accepted + SSE progress streaming. |
| Push notifications | codehome | VAPID keys, Web Push subscriptions, notification delivery, preferences. Uses wesktop's background task registry. |
| MCP | codehome | FastMCP with role-based tools. Stays in codehome until a second consumer needs it. |
| Config identity | codehome | ~/.codehome/config.toml. codehome owns its config location. |
| CLI framework | codehome | argparse with dynamic plugin command registration from 21 plugin manifests. |
| Plugin SDK | codehome | Two-tier _sdk pattern (codehome.sdk + per-plugin _sdk.py). Clean up and formalize during migration. |

### Migration parameters

- Both projects migrate in parallel (codehome + CT).
- Routes and server replaced simultaneously (no intermediate hybrid).
- Desktop window (pywebview) is primary mode for codehome.
- Plugin manifests stay TOML (plugin.toml).
- All 12 route-bearing plugins migrate at once. No rollback strategy; leap of faith.
- No backward-compat requirement beyond migrating the 21 plugins at ~/Work/super/plugins/.
- Dual publishing continues (PyPI + NPM) for codehome.
- Plugin auth: separate public/private routers (same pattern as today).
- OpenAPI/docs: deferred entirely. Not on migration critical path.
- CT frontend keys on "detail" only. codehome frontend keys on detail > message > error. Both already work with {"detail": "..."}.

---

## Phase 0: Groundwork

### 0.1 Granian cold-start benchmark

Run Granian serving a minimal ASGI app. Measure time from process spawn to first HTTP 200. Target: under 500ms for the reload feature in Phase 2.6.

**Verify:** printed benchmark numbers with methodology.

### 0.2 Granian asyncio.create_task compatibility

codehome's services router uses fire-and-forget asyncio.create_task() for 202 Accepted patterns — the handler returns immediately, the task runs in the background. These tasks must outlive the request handler. Verify that Granian's worker model supports persistent asyncio tasks on the event loop (tasks created during a request survive after the response is sent). If Granian uses per-request event loops or worker recycling, this pattern breaks.

**Verify:** start Granian serving a test app. Handler creates a task that writes to a file after 2 seconds, returns 202 immediately. After 3 seconds, the file exists.

### 0.3 strictcli config API audit

Read strictcli source to understand how config=True works: storage location, schema declaration, subcommands. Determine whether apps can declare their own config identity (codehome at ~/.codehome/, CT at its own path) rather than using ~/.config/wesktop/.

**Verify:** written summary of strictcli config API with gaps identified. If strictcli cannot support app-owned config paths, identify what needs changing.

### 0.4 wesktop test infrastructure

wesktop tests use pytest-anyio and httpx.ASGITransport. Add a conftest.py fixture that creates a wesktop app and returns an async httpx client. This becomes the foundation for the TestClient shipped in Phase 7.1.

**Verify:** fixture exists, all Phase 1+ tests use it.

### 0.5 Dependency audit

List every Python package that codehome and CT currently get transitively through FastAPI/Starlette that they use directly. These become explicit dependencies or need replacement.

codehome uses: starlette.requests.Request, starlette.responses.*, fastapi.Depends, fastapi.APIRouter, fastapi.HTTPException, fastapi.security.HTTPBearer, fastapi.Cookie, fastapi.Body, starlette.middleware.cors.CORSMiddleware.

CT uses: starlette.middleware.trustedhost.TrustedHostMiddleware, starlette.testclient.TestClient, plus the same FastAPI/Starlette surface as codehome.

**Verify:** list of packages with disposition (keep as explicit dep / replace with wesktop equivalent / drop).

---

## Phase 1: Router and request/response foundations

All changes in wesktop/src/wesktop/asgi.py unless noted. Each subphase has its own tests.

### 1.1 Body reading for all methods

Currently line 365 gates body reading on `method == "POST"`. Change to always read body regardless of method. GET with an empty body costs nothing; DELETE with a body becomes possible.

**Verify:** test sends DELETE with JSON body, handler reads req.json successfully. GET with no body still works (req.json is None or empty).

### 1.2 query_list(name)

Request.query() at line 113 calls parse_qs (returns lists) but discards all but the first value. Add query_list(name, type_=str) method returning the full list with optional type coercion. query() stays single-value.

**Verify:** test sends ?tag=a&tag=b, req.query_list("tag") returns ["a", "b"]. req.query_list("tag", type_=int) on ?tag=1&tag=2 returns [1, 2].

### 1.3 Query parameter validation

Extend Request.query() to accept constraint kwargs: ge, le, min_length, max_length. Validate after type coercion. Raise HTTPError(422) with detail describing the violation.

**Verify:** ?limit=-1 to a route using req.query("limit", type_=int, ge=0) returns 422 with detail.

### 1.4 Path parameter type coercion

Router segment matching at line 184 treats {param} as string-only. Add {param:int} syntax. During add_route, parse segment format and store expected type. During match, attempt coercion; return None (no match) on failure. Also support {param:str} as explicit default.

**Verify:** route /{id:int} matches /42 with params["id"] == 42 (int, not str). /abc returns 404.

### 1.5 HTTPError exception and error format

Introduce HTTPError exception class with status_code and detail fields. Change the exception handler in create_app to catch HTTPError and return {"detail": detail} with the right status. Change the generic 500 from {"error": ...} to {"detail": ...}. Change the 404 fallback similarly.

**Verify:** handler raises HTTPError(404, "not found"), client receives {"detail": "not found"} with status 404. Unhandled exception returns {"detail": "Internal server error"} with status 500.

### 1.6 Exception handler registry

Add exception_handlers parameter to create_app(): a dict mapping exception types to handler callables. When a handler raises, check the exception type against the registry (most specific first) before falling through to the generic 500.

**Verify:** register handler for ValueError that returns 422. Handler raises ValueError. Client gets 422 with {"detail": ...}.

### 1.7 WebSocket path parameters and app-scoped routing

Refactor _ws_routes from module-level global dict to app-scoped (on the Router or inside the create_app closure). Currently multiple apps in the same process (e.g., tests) share WS routes, causing interference. Then extend WS route matching to use the same segment matching as Router.match(). add_ws_route("/ws/{session_id}", handler) captures params. Params accessible on the WebSocket helper (Phase 1.8) or in scope.

**Verify:** WebSocket connects to /ws/abc123, handler receives path_params["session_id"] == "abc123". Two apps in the same process have independent WS route tables.

### 1.8 WebSocket helper class

New class WebSocket wrapping ASGI (scope, receive, send). Methods: accept(), close(code), send_json(data), send_bytes(data), send_text(text), receive_json(), receive_bytes(), receive_text(). Properties: path_params, query_string, headers. Handlers receive this instead of raw triple.

**Verify:** echo test: client sends JSON via WebSocket, server receives via ws.receive_json(), echoes via ws.send_json(), client receives it back.

### 1.9 PUT and PATCH method decorators

Router has get, post, delete but no put or patch. codehome needs PATCH for password change, PUT for feature flag updates. Add @router.put(path) and @router.patch(path).

**Verify:** PUT and PATCH routes match and their handlers execute.

### 1.10 Router composition and prefix mounting

codehome uses include_router(router, prefix="/api/p/{plugin_name}") extensively for plugin routes and include_router(router, dependencies=[Depends(get_current_user)]) for blanket auth. Add Router.include_router(other_router, prefix=None) that merges all routes from other_router, prepending prefix to each path. Add router-level dependencies that apply to all routes in a router (resolved before per-handler deps). This enables the separate public/private router pattern without per-handler auth decoration.

**Verify:** sub-router with GET /status mounted with prefix="/api/v1" responds at /api/v1/status. Router-level dependency runs for all routes in that router. Routes in a sub-router without the dependency are not affected.

### 1.11 Lifespan state and request.state

wesktop's create_app lifespan parameter currently supports async context managers but does not propagate state to requests. Change: if the lifespan context manager yields a dict, merge it into scope["state"] for every incoming HTTP and WebSocket request. Add a .state property to Request and WebSocket that returns a State wrapper object (not a raw dict). The State wrapper supports both attribute access (req.state.db = conn) and dict access (req.state["db"]) — codehome uses attribute assignment (request.state._user = claims) while middleware uses dict access (state.get("_user")). A raw dict would fail on attribute assignment. Initialize scope["state"] as empty dict if no lifespan state exists.

Also add convenience properties to Request: .method (from scope["method"]), .path (from scope["path"]). Both consumers use these pervasively.

Also add request.is_disconnected() async method. Checks the ASGI receive channel for http.disconnect. Needed for SSE heartbeat loops to detect dead connections and stop leaking coroutines.

**Verify:** lifespan yields {"db": "test"}. Handler accesses req.state["db"] and req.state.db — both return "test". req.state.custom = "val" works (attribute assignment). req.method returns "GET". req.path returns "/api/health". SSE handler calls await req.is_disconnected() — returns False while client connected, True after client disconnects.

### 1.12 StreamResponse status code

StreamResponse currently hardcodes status 200. Add optional status parameter (default 200). codehome's services router returns 202 Accepted with streaming body for async operations.

**Verify:** StreamResponse(generator, status=202) sends 202 status code. Default remains 200.

### 1.13 ASGI helpers and type aliases

Add send_error(send, status, detail) helper for middleware to send JSON error responses without constructing raw ASGI messages. Add canonical type aliases: Scope = dict[str, Any], Receive = Callable, Send = Callable. Export from wesktop for use by all middleware (built-in and consumer-provided).

**Verify:** middleware calls send_error(send, 403, "forbidden"), client receives {"detail": "forbidden"} with status 403.

### 1.14 Response headers and cookies

wesktop's JSONResponse has no headers parameter. FastAPI handlers set cookies via an injected mutable Response object (response.set_cookie()). wesktop needs a different mechanism. Add optional headers dict and cookies list to all response types (JSONResponse, TextResponse, HTMLResponse, BytesResponse, StreamResponse). Add convenience helpers: set_cookie(name, value, httponly, samesite, max_age, path, secure) produces a Set-Cookie header string. delete_cookie(name, path) produces a Set-Cookie with max_age=0 (codehome's logout handler uses response.delete_cookie("session")).

This replaces FastAPI's pattern of mutating an injected Response object. Instead: build the response with cookies included.

**Verify:** handler returns JSONResponse(data, cookies=[set_cookie("session", token, httponly=True)]). Client receives JSON body with Set-Cookie header. handler returns JSONResponse(data, cookies=[delete_cookie("session")]). Cookie is cleared. Handler returns JSONResponse(data, headers={"X-Custom": "val"}). Client receives the custom header.

### 1.15 Cookie extraction on Request

wesktop's Request has no cookie parsing. codehome's auth reads the session cookie via Cookie(default=None). Add req.cookies property returning a dict parsed from the Cookie header (using http.cookies.SimpleCookie). Add req.cookie(name, default=None) convenience method.

**Verify:** request with Cookie: session=abc123 header, req.cookie("session") returns "abc123". req.cookie("missing") returns None. req.cookies returns {"session": "abc123"}.

### 1.16 {key:path} path converter

codehome's services router uses {key:path} in 10+ endpoints to match paths containing slashes (e.g., branch-name/vite-app). wesktop's router splits on / and counts segments, so {key:path} fundamentally breaks segment-count matching. Add :path type that greedily matches all remaining segments (joined with /). Must be the last parameter in the route pattern. Changes the matching algorithm: when a :path segment is encountered, all remaining path segments are consumed.

**Verify:** route /api/services/{key:path}/start matches /api/services/main/vite-app/start with params["key"] == "main/vite-app". Route /{rest:path} matches /a/b/c with params["rest"] == "a/b/c".

### 1.17 FileResponse

Add FileResponse(path, content_type=None, status=200) that serves a file from disk. Auto-detects MIME type if not provided. Sets Content-Length from file size. Reads in chunks for memory efficiency (or uses sendfile if supported). codehome's branding endpoint and static file serving use this.

**Verify:** FileResponse pointing to a real file returns the file content with correct Content-Type and Content-Length headers.

### 1.18 query_params property and coercion failure

Add Request.query_params property returning the full parsed dict (all keys, first value per key). codehome's auth reads request.query_params.get("token"). Also change query() behavior: type coercion failure (e.g., ?limit=abc with type_=int) raises HTTPError(422) instead of silently returning default. Explicit default=X is only used when the key is absent, not when coercion fails.

**Verify:** req.query_params.get("token") returns the token value. ?limit=abc with type_=int raises 422. ?limit absent with default=10 returns 10.

### 1.19 Middleware constructor API

wesktop's create_app accepts middleware as list[type] and instantiates each with just the inner app (asgi.py line 409). But configured middleware (CORS, TrustedHost, etc.) needs constructor args. Change the middleware parameter to accept list[Callable] — either classes or pre-configured factory functions. Built-in middleware (auto-wired via create_app parameters) bypasses this parameter entirely. User-provided middleware passes pre-configured instances or factories.

**Verify:** custom middleware class with constructor args can be passed as a lambda or partial to create_app middleware parameter.

---

## Phase 2: Server lifecycle

Changes in wesktop/src/wesktop/server.py and __init__.py. Independent of DI; can run in parallel with Phase 3.

### 2.1 serve(foreground) with no default

Merge start_server and start_server_in_background into a single serve() function. foreground is a required bool parameter (no default). When True, blocks. When False, spawns daemon thread and returns URL string. This is a breaking change to wesktop's existing public API (which had host/port defaults and separate start_server/start_server_in_background functions).

serve() currently takes a string target (e.g., "myapp:app") because Granian needs to import the app in worker processes. But create_app() returns a callable built at runtime. To reconcile: serve() also accepts a callable directly. When given a callable, wesktop writes a thin wrapper module to a temp location that Granian can import, or uses Granian's programmatic API to pass the app object directly (Granian supports this). When given a string, it passes through to Granian as today.

Multi-worker concern: codehome creates its app at module level with side effects (plugin loading, router mounting). If Granian spawns multiple workers via string target, each worker re-imports and re-runs plugin loading (designed to run once). Either: use single-worker mode (fine for localhost dev tools), or pass a callable (avoids re-import but requires Granian's programmatic API).

**Verify:** serve(target=app, foreground=False) where app is a create_app() result — server starts and responds. serve(target="myapp:app", foreground=True) — also works (string path).

### 2.2 stop(pid_path)

New function. Reads PID from file, sends SIGTERM, waits up to 10s polling with os.kill(pid, 0), escalates to SIGKILL if still alive. Cleans up PID file. Raises FileNotFoundError if PID file missing, ProcessLookupError if process already gone.

**Verify:** start server in background, call stop(), verify process gone and PID file removed.

### 2.3 status(pid_path, health_url)

New function returning a dataclass with fields: running (bool), pid (int or None), healthy (bool or None). Checks PID liveness via os.kill(pid, 0). If running, probes health_url with a short timeout and sets healthy accordingly.

**Verify:** start server, status() returns running=True with correct pid and healthy=True. Stop server, status() returns running=False.

### 2.4 Pre-serve callback

Add pre_serve parameter to serve(). Callable, invoked synchronously after PID/port checks but before Granian starts. Use case: codehome loads plugins, CT runs npm build.

**Verify:** pre_serve sets a flag file, server starts, flag file exists on disk.

### 2.5 Env var settings

serve() reads {NAME}_HOST and {NAME}_PORT where NAME is derived from the name parameter (uppercased). Explicit function args override env vars. If neither arg nor env var is provided, raise ValueError (no implicit defaults for host or port).

**Verify:** set WESKTOP_PORT=9999, call serve() without port arg, server binds to 9999. Call with no port arg and no env var, get ValueError.

### 2.6 Reload (conditional on Phase 0.1)

If Granian cold start < 500ms: implement serve(reload=True) using watchfiles to restart the Granian process on source changes. If Granian is too slow: use watchfiles with a thinner wrapper that reimports the ASGI target module without full process restart. Either way the user API is serve(reload=True).

**Verify:** start with reload=True, modify a Python file, server restarts and serves updated response.

---

## Phase 3: Dependency injection

New module wesktop/src/wesktop/di.py. Most design-intensive phase.

### 3.1 DI core: dependency declaration and resolution

Design the DI API. Requirements derived from both consumers:

- Dependencies are callables (sync or async) that receive the request object.
- Generator dependencies (with yield) get cleanup after the handler returns. CT's get_conn() yields a SQLite connection and closes it in finally.
- Dependencies can depend on other dependencies (chaining). codehome's require_admin depends on get_current_user.
- Results are cached per-request: same dependency called twice returns the same instance.
- Works for both HTTP and WebSocket handlers.

The API design itself (decorator kwargs, type annotations, or request method) is resolved during implementation of this subphase. The chosen API must be documented with examples before proceeding to 3.2.

**Verify:** route handler declares a dependency on a factory function. DI resolves it per-request. Generator dependency's cleanup runs after response is sent. Two handlers in one request sharing a dependency get the same instance.

### 3.2 DI integration with create_app

Wire DI into the request handling path inside create_app(). Before calling the handler, resolve declared dependencies. After handler returns (or raises), run cleanup for generator deps (in reverse order). Same for WebSocket handlers.

**Verify:** handler with two deps (one sync, one async generator) receives both. Generator cleanup confirmed via side effect (e.g., flag set in finally block). WebSocket handler with a dep receives the resolved value.

### 3.3 Feature-gated dependencies

Some dep factories raise HTTPError when a feature is disabled (codehome's get_pty_manager returns 503 if terminal feature is off). DI must propagate HTTPError from dep factories before calling the handler. The handler never executes if a dependency fails.

**Verify:** dep factory raises HTTPError(503, "feature disabled"). Client gets 503. Handler did not execute (confirmed via side effect).

### 3.4 Dependency overrides for testing

codehome's test suite relies on FastAPI's app.dependency_overrides dict to swap real dependencies with test doubles. wesktop's DI must support the same pattern: a dict mapping dep factories to replacement factories. When set, the override runs instead of the original. TestClient (Phase 7.1) must support overrides.

**Verify:** override get_conn with a factory that returns an in-memory SQLite connection. Handler receives the test connection, not the production one. Overrides are scoped to the test (don't leak between tests).

---

## Phase 4: Auth module

New module wesktop/src/wesktop/auth.py. Depends on Phase 3 (DI).

### 4.1 JWT token operations

Pure functions: create_token(username, role, secret, expires_hours) returns JWT string. verify_token(token, secret) returns claims dict or None. HS256 via PyJWT. Claims: sub, role, iat, exp.

**Verify:** create token, verify it, get claims. Expired token returns None. Tampered token returns None.

### 4.2 Password hashing

Pure functions: hash_password(plain) returns bcrypt hash string. verify_password(plain, hashed) returns bool.

**Verify:** hash, verify correct password (True), verify wrong password (False).

### 4.3 User storage interface

Abstract interface: load_users(), save_users(users), find_user(username). Default implementation: JSON file at a caller-specified path. Each user: username, password_hash, role, created_at.

**Verify:** create user, find_user returns it, list users includes it. JSON file written to specified path.

### 4.4 Auth dependencies

get_current_user as a wesktop DI dependency. Token resolution order: Authorization Bearer header, session cookie, ?token= query param. Returns claims dict (sub, role). Raises HTTPError(401) if no valid token. require_role(role) as a chained dependency that checks claims["role"].

codehome adds its own fourth source (CLI token file at ~/.codehome/token) by wrapping wesktop's get_current_user.

**Verify:** Bearer token request authenticated. Cookie request authenticated. Query param request authenticated. No token returns 401. require_role("admin") with non-admin user returns 403.

### 4.5 CSRF double-submit middleware

Port codehome's csrf.py (already pure ASGI, ~95 lines). Safe methods (GET, HEAD, OPTIONS) exempt. Bearer token callers exempt (structural check: 3 dot-separated segments). Configurable exempt paths. Validates csrf_token cookie matches X-CSRF-Token header.

Portability notes: codehome's CSRF accesses scope["app"] to check csrf_disabled — wesktop has no scope["app"]. Replace with middleware config (pass disabled flag at construction or read from app state via scope["state"]). codehome's CSRF also checks the CLI token file (~/.codehome/token) — this stays in codehome's wrapper; wesktop's CSRF is generic.

Use the send_error() helper (Phase 1.13) for error responses instead of manually constructing ASGI messages.

**Verify:** POST without CSRF token returns 403. POST with matching cookie + header passes. GET always passes. Bearer auth passes without CSRF.

### 4.6 Session cookie helpers

Utility functions for login/logout cookie management: set_session_cookies(response, token, csrf_token) sets session (httponly, samesite=lax) and csrf_token (js-readable) cookies. clear_session_cookies(response) clears both. Not a full login endpoint; apps wire their own login handlers using these helpers.

**Verify:** set cookies, subsequent request has both cookies. Clear cookies, subsequent request has neither.

### 4.7 Rate limiting

Decorator-based rate limiter. @rate_limit("5/minute") on handler functions. The decorator wraps the handler: it extracts the Request from the first positional arg, derives the client key (IP by default, or custom key function), checks the token bucket, and raises HTTPError(429) before calling the original handler if the limit is exceeded. Applied inside the route decorator (so DI resolution has already happened), meaning the rate limit check runs after auth but before handler logic. No middleware; SSE endpoints simply don't get the decorator.

**Verify:** endpoint limited to 5/minute. 6th request within 60s returns 429. Unlimited endpoint works normally.

---

## Phase 5: Middleware and observability

Depends on Phase 1 (router, HTTPError). Can run in parallel with Phases 3-4.

### 5.1 structlog integration

New module wesktop/src/wesktop/logging.py. Configure structlog with sensible defaults. Shared processors: merge contextvars, add log level, ISO timestamps, callsite info (module, function, line). Renderer: JSON if not isatty, colored console if isatty. Expose configure_logging() called automatically by serve().

**Verify:** serve() starts, handler logs a message, output is structured JSON with timestamp and log level.

### 5.2 Request ID middleware

Pure ASGI middleware. Clears structlog contextvars at the start of each request (prevents context leaking between requests). Extracts X-Request-Id from incoming request or generates UUID4. Stores in scope["state"]["request_id"]. Binds to structlog contextvars (automatically included in all log entries for that request). Injects X-Request-Id into response headers.

**Verify:** request without ID gets response with X-Request-Id UUID header. Request with X-Request-Id header gets it echoed. Log entries contain request_id. Context from request N does not appear in request N+1 logs.

### 5.3 Request timing middleware

Pure ASGI middleware. Captures status code from http.response.start. Measures wall-clock duration. Logs structured entry (method, path, status, duration_ms, user if available). Maintains ring buffer of recent requests (configurable maxlen, default 10k). Excludes configurable long-lived paths (SSE, WebSocket) from ring buffer. On 5xx responses, escalates to the SQLite error log (Phase 5.8) if configured — the timing middleware holds a reference to the error log instance (passed via middleware config or app state).

**Verify:** make requests, ring buffer contains entries. Log output shows method/path/status/duration_ms. 5xx response writes to error log.

### 5.4 CORS middleware

Pure ASGI CORS middleware. Handles preflight OPTIONS requests. Sets Access-Control-Allow-Origin, Methods, Headers, Credentials. Configured via create_app(cors_origins=["http://localhost:5173"]).

**Verify:** preflight OPTIONS from Vite origin returns correct CORS headers. Normal request has Access-Control-Allow-Origin.

### 5.5 TrustedHost middleware

Pure ASGI middleware. Rejects requests whose Host header is not in an allowed set. Blocks DNS rebinding attacks for localhost servers. Configured via create_app(trusted_hosts=["localhost", "127.0.0.1"]).

**Verify:** request with Host: localhost passes. Request with Host: evil.com returns 400.

### 5.6 Built-in middleware wiring

create_app() gains parameters for auto-adding middleware in the correct order: cors_origins (adds CORS), trusted_hosts (adds TrustedHost), request_id (bool, default True), request_timing (bool, default True). Order from outer to inner: TrustedHost, CORS, RequestID, RequestTiming.

**Verify:** app created with defaults has request ID and timing. Passing cors_origins adds CORS. Passing trusted_hosts adds TrustedHost.

### 5.7 Error tracking (Sentry)

Optional Sentry integration. If sentry-sdk is installed and a DSN is provided (via app config or env var), initialize Sentry with ASGI integration (not the FastAPI-specific integration). Enrich with request context (method, path, query, headers) and user context (from auth, if available). Auto-capture unhandled exceptions. Filter out HTTPError 4xx responses in before_send (replace the current starlette.exceptions.HTTPException filter). codehome's pyproject.toml must change from sentry-sdk[fastapi] to plain sentry-sdk to avoid transitively pulling FastAPI back in.

**Verify:** configure DSN, raise unhandled exception, Sentry receives the event (or mock confirms capture was called). HTTPError(404) does not trigger Sentry. No fastapi or starlette in sentry-sdk's installed dependencies.

### 5.8 SQLite error log

New module. Append 5xx errors to a SQLite database with: timestamp, method, path, status_code, detail, request_id, user, traceback. Request timing middleware (5.3) escalates 5xx responses to this log. Configurable file path. Auto-creates table on first write.

**Verify:** handler raises exception, 500 returned, error log contains entry with traceback and request context.

---

## Phase 6: Pydantic integration

Depends on Phase 1 (router, HTTPError).

### 6.1 response_model on routes

Route decorators gain optional response_model parameter. After handler returns a dict, if response_model is set: validate via model.model_validate(), serialize via model.model_dump(mode="json"). Validation failure is a server bug (500), not client error.

**Verify:** handler returns valid dict, response matches model schema. Handler returns invalid dict (missing field), response is 500 with detail.

### 6.2 Request body parsing with Pydantic

Add req.json_as(Model) method. Calls Model.model_validate(req.json). Raises HTTPError(422) with field-level validation errors on failure.

**Verify:** POST with valid JSON returns model instance. POST with missing required field returns 422 with field name in detail.

---

## Phase 7: Dev experience

### 7.1 TestClient

New module wesktop/src/wesktop/testing.py. Wraps httpx.AsyncClient with ASGITransport. Provides both sync (TestClient) and async (AsyncTestClient) interfaces. httpx is a dev/test dependency (not runtime). Runs lifespan on enter, shuts down on exit.

**Verify:** TestClient(app).get("/health") returns response without starting a real server. Lifespan runs (confirmed via side effect).

### 7.2 Vite dev proxy

Port codehome's ViteProxyMiddleware (already pure ASGI). create_app(vite_dev_port=5173) adds middleware. Non-API requests proxy to Vite. API requests (configurable prefix, default /api/) pass through to app. WebSocket connections proxy for HMR.

**Verify:** Vite running on 5173, proxy forwards / to Vite (HTML response), /api/health goes to app (JSON response). HMR WebSocket connects through proxy.

### 7.3 Config via strictcli

Based on Phase 0.3 audit results. Apps pass config_name to wesktop, which determines the config directory. strictcli provides show/set/edit/path subcommands that apps can mount on their CLI. If strictcli cannot support app-owned paths, this subphase includes modifying strictcli.

**Verify:** codehome config show prints config from ~/.codehome/. CT config show prints config from its own path.

---

## Phase 8: Advanced features

### 8.1 Feature flags

New module wesktop/src/wesktop/features.py. Apps declare flags with defaults at startup. Overrides loaded from a JSON file (path provided by app). API: enabled(name) returns bool, all_flags() returns dict, set_override(name, value) persists to file, reload() re-reads file.

**Verify:** flag "terminal" default False, override file sets True, enabled("terminal") returns True. Delete override file, reload(), enabled("terminal") returns False.

### 8.2 Audit logging

New module wesktop/src/wesktop/audit.py. Append-only JSONL writer. Each entry: ISO timestamp, event_type (string), payload (dict, app-defined). Configurable file path. Thread-safe (lock on write). Optional size-based rotation.

**Verify:** log 3 events, read JSONL file, find all 3 with timestamps and correct payloads.

### 8.3 Background task registry

New module wesktop/src/wesktop/tasks.py. Protocol: tasks implement start() and stop(). Registry: register(name, factory, feature=None), start_all(), stop_all(), list_tasks(), get_task(name). Feature-gated tasks skip when flag disabled. Lifecycle tied to serve() via lifespan (start_all on startup, stop_all on shutdown).

**Verify:** register two tasks, start_all(), both running (confirmed via side effect). stop_all(), both stopped. Feature-gated task with disabled flag is skipped.

### 8.4 SDUI primitives

Port codehome's 39 Pydantic models from src/codehome/serve/sdui/primitives.py into wesktop. Organized by category: layout (Stack, ZStack, Spacer, Divider, Grid, Card, Tabs, Breadcrumb, Empty), display (Heading, Text, Code, Status, Badge, ProgressBar, Spinner, Timeline, Diff, Markdown), data (Table, List, KeyValue, JsonView, Tree), input (Button, Input, TextArea, Select, Checkbox, Switch, Radio, Slider), feedback (Alert, Toast, Logs), overlay (Modal, Drawer, Popover, Confirm). Each has .to_node() serialization. Provider registry: register_sdui_provider(name, async_fn) where fn returns (ui_tree, initial_state) tuple.

**Verify:** create Stack containing Heading and Button, serialize via .to_node(), get valid dict. Register provider, call it, get tree and state back.

---

## Phase 9: codehome core migration

Depends on Phases 1-8. All subphases are sequential.

### 9.1 Create wesktop-based app factory

Replace FastAPI(title=..., lifespan=lifespan) in src/codehome/serve/server.py with wesktop.create_app(router, ...). Port the lifespan context manager to wesktop's lifespan parameter. Lifespan yields a state dict containing all singletons (event_manager, service_manager, port_allocator, config, etc.). Handlers access via req.state or DI.

**Verify:** codehome server start launches wesktop/Granian instead of FastAPI/uvicorn. GET /api/health responds with 200.

### 9.2 Migrate middleware stack

Replace manually-added middleware with wesktop built-ins: request_id=True, request_timing=True, cors_origins=[...], trusted_hosts=[...]. Port CSRF to wesktop's auth CSRF middleware (Phase 4.5). Remove slowapi; replace with wesktop's @rate_limit decorator on login endpoint. Remove all Starlette imports from middleware.py.

**Verify:** request has X-Request-Id header. Timing logged to structlog. CSRF enforced on POST. Login endpoint rate-limited.

### 9.3 Migrate auth to wesktop auth module

Replace codehome.serve.auth_deps.get_current_user with wesktop's auth DI dependency (Phase 4.4). Wrap it to add the fourth token source (CLI token file at ~/.codehome/token). Replace require_admin with require_role("admin"). Update every file that imports from auth_deps.

**Verify:** login sets JWT cookies. Subsequent request authenticated. CLI token file authentication works. Admin-only endpoint rejects non-admin.

### 9.4 Migrate core routers

Rewrite each of the 7 core routers from FastAPI APIRouter to wesktop Router:
- auth.py (182 lines): login, logout, me, user CRUD. Rate-limited login.
- system.py: health, diagnostics, branding, server info.
- features.py (45 lines): feature flag list, reload, update.
- plugins.py: plugin listing, SDUI tree retrieval, command dispatch.
- services.py (810 lines): Docker lifecycle with 202 Accepted + OperationTracker, deps management. Most complex router.
- conductor.py: agent session lifecycle, chat, planning.
- agents.py: task agent dispatch, session listing.

For each route: replace @router.get/post/put/patch/delete with wesktop decorators, replace Depends(...) with wesktop DI, replace HTTPException with HTTPError, replace Body() with req.json_as(Model), replace JSONResponse with wesktop response types.

Separate public and authenticated routers per the existing pattern. Mount authenticated routers with get_current_user DI dependency.

Migration mechanic: every `await request.json()` callsite (FastAPI/Starlette async method) must change to `request.json` (wesktop synchronous property, no await, no parentheses). Missing this causes TypeError at runtime.

**Verify:** before migration, capture golden files of endpoint responses (status codes, response shapes for known inputs) for each core router. After migration, verify migrated endpoints match golden files exactly. This avoids circular testing (rewriting tests and code simultaneously).

### 9.5 Migrate SSE

codehome's EventManager stays as-is (own class, own client management, push integration, heartbeat). The SSE endpoint handler changes from FastAPI's StreamingResponse to wesktop's StreamResponse. The EventManager.subscribe() async generator feeds into StreamResponse.

**Verify:** dashboard connects to SSE endpoint, receives heartbeats every 15s, receives broadcast events when they fire.

### 9.6 Migrate WebSocket terminal endpoint

Port the terminal WebSocket from FastAPI @router.websocket to wesktop add_ws_route with path params ({session_id}). Use wesktop's WebSocket helper class for send/receive. Auth via query param token verification inside handler (same pattern as today).

**Verify:** WebSocket connects to /api/terminal/{session_id}/ws?token=..., PTY input/output flows bidirectionally, resize control messages work.

### 9.7 Migrate static files and Vite proxy

Replace codehome's static_files.py (FastAPI catch-all router) with wesktop's spa_fallback parameter in create_app(). Replace codehome's ViteProxyMiddleware with wesktop's built-in dev proxy (vite_dev_port parameter).

**Verify:** production mode: SPA serves index.html for unknown GET routes, /assets/ serves static files. Dev mode: Vite HMR works, API routes pass through to app.

### 9.8 Wire desktop window

Add pywebview launch as the primary mode for codehome open. Server starts in background via wesktop.serve(foreground=False), then pywebview opens dashboard URL in native window. Add --browser flag as fallback to open browser tab instead. Server shutdown on window close.

**Verify:** codehome open launches native OS window showing dashboard. codehome open --browser opens browser tab. Closing native window shuts down server.

### 9.9 Remove FastAPI/Starlette/uvicorn

Delete fastapi, starlette, and uvicorn from pyproject.toml dependencies. Add wesktop as dependency. Grep entire codebase for remaining imports and remove them. Delete any now-empty compatibility modules.

**Verify:** pip install -e . succeeds without FastAPI. python -c "import codehome" succeeds. grep -r "from fastapi\|from starlette\|import uvicorn" finds nothing.

---

## Phase 10: codehome plugin SDK and route migration

Depends on Phase 9 (core migration complete).

### 10.1 Formalize plugin SDK

Clean up codehome/sdk.py: audit the 51-symbol lazy import map, remove dead exports, remove references to FastAPI-specific helpers. Point auth deps (get_current_user, get_gh_token) to wesktop auth equivalents (or codehome's wrapper). Document the stable plugin API surface.

**Verify:** every symbol in the lazy import map resolves. No imports from fastapi or starlette anywhere in sdk.py.

### 10.2 Update per-plugin _sdk.py files

All 20 per-plugin _sdk.py files curate subsets of codehome.sdk. Update any that import auth deps or other migrated symbols. Standardize: ensure each has __all__, remove unused imports, remove any direct FastAPI imports.

**Verify:** from _sdk import get_current_user resolves to wesktop auth dep (or codehome's wrapper). No plugin _sdk.py imports FastAPI or Starlette.

### 10.3 Migrate all 12 plugin routes.py files

Rewrite all at once. For each of the 12 plugins with routes.py (core, dashboard, deploy, design, figma, figma2sdui, linear, review, supabase, tdd, team, telemac):

- Replace from fastapi import APIRouter, HTTPException, Depends with wesktop equivalents.
- Replace from starlette.requests import Request with from wesktop import Request.
- Replace @router.get/post/... with wesktop route decorators.
- Replace Depends(get_current_user) with wesktop DI.
- Replace HTTPException(status, detail=...) with HTTPError(status, detail).
- Replace JSONResponse / StreamingResponse with wesktop response types.

Additionally, rewrite the SDUI command dispatch in plugins.py (lines 121-157). This code introspects FastAPI router internals (route.path, route.methods, route.endpoint) and uses inspect.signature to hand-resolve handler dependencies (pattern-matching on EventManager, BaseModel, etc.). This is a hand-rolled mini-DI system against FastAPI internals. It must be rewritten to either use wesktop's DI resolution API directly or to match against wesktop's Router internal structure.

**Verify:** each plugin's routes respond correctly. Start codehome server, hit representative endpoints from each plugin. SDUI command dispatch from dashboard triggers correct plugin route handler.

### 10.4 Migrate SDUI providers

Port telemac's _telemac_sdui_provider to wesktop's SDUI provider registry (Phase 8.4). Update the plugins router SDUI endpoint to use wesktop's register_sdui_provider / provider lookup.

**Verify:** GET /api/plugins/telemac returns SDUI tree and initial state matching current behavior.

---

## Phase 11: ClaudeTimeline migration

Can run in parallel with Phases 9-10. Depends on Phases 1-8.

### 11.1 Create wesktop-based app

Replace CT's FastAPI(title=..., lifespan=lifespan) with wesktop.create_app(). Port lifespan (database existence check). Middleware: CORS via wesktop, TrustedHost via wesktop, request logging via wesktop's timing middleware.

Rate limiting behavioral change: CT currently has global 120/minute via SlowAPI middleware on ALL endpoints. Moving to per-handler @rate_limit means you must explicitly decorate sensitive endpoints. The global safety net is dropped. Either accept this or add @rate_limit to all endpoints.

CT gets pydantic transitively from FastAPI. After removing FastAPI, CT gets it transitively from wesktop (which adds pydantic in Phase 6). This chain should work but CT should also add pydantic as an explicit direct dependency in its own pyproject.toml to avoid surprise breakage if wesktop ever makes pydantic optional.

**Verify:** claudetimeline serve run starts on Granian, GET /api/health responds 200.

### 11.2 Migrate DI dependencies

Port get_conn() (generator yielding SQLite connection with PRAGMA setup, closes in finally), get_annotations_conn() (same pattern for read-write DB) to wesktop DI factories. Generator pattern must work: connection opened before handler, closed after handler returns.

parse_filters() is deeply FastAPI-specific: it uses Query() objects as function parameter defaults that FastAPI introspects and resolves from query params. It never receives a Request object. This must be rewritten as a function that accepts a wesktop Request and manually parses each filter parameter using req.query() and req.query_list(). The rewritten function then becomes a wesktop DI factory.

**Verify:** handler receives SQLite connection, queries succeed, connection closed after response. parse_filters returns correct filter values from query params. Constraints (ge, le) validated.

### 11.3 Migrate routes (29 modules, ~69 handlers)

Rewrite all route files from FastAPI to wesktop. CT has ~29 response_model usages across endpoints that must also be migrated to wesktop's response_model decorator parameter.

Batch 1 (trivial, ~25 routes): single GET, no body, just conn dependency. Pattern: req.query() for params, SQL query, return dict.

Batch 2 (medium, ~25 routes): conn + filters dependencies, pagination, cursor logic, multi-value query params (uses query_list), response_model validation.

Batch 3 (complex, ~19 routes): POST with Pydantic body models (req.json_as(Model)), SSE streaming (jobs), admin endpoints, dual-database access (conn + annotations_conn), manage actions with confirm tokens.

Migration mechanic: every `await request.json()` must become `request.json` (property, no await). Every `response_model=SomeModel` on a decorator must become wesktop's equivalent.

**Verify:** capture golden files of current endpoint responses before migration. After migration, verify responses match. Run adapted test suite.

### 11.4 Migrate exception handlers

Port sqlite3.OperationalError handler (returns 503 with {"detail": "Database unavailable: ..."}) and catch-all Exception handler (logs traceback, returns 500 with {"detail": "Internal server error"}) to wesktop's exception handler registry.

**Verify:** database file missing at runtime returns 503. Unhandled exception returns 500 and traceback appears in log.

### 11.5 Migrate SSE job streaming

Port CT's job system SSE endpoint to wesktop's StreamResponse. Job manager (jobs.py) stays unchanged; it produces an async generator. SSE format: event: log with data per line, event: done with {"exit_code": N}. 15-second heartbeat keepalive. Note: CT needs heartbeat in its SSE stream (same as codehome). If wesktop's Broadcaster gains heartbeat_interval support (useful for any SSE consumer), CT can use Broadcaster directly. Otherwise CT implements heartbeat in its own async generator (same pattern as codehome's EventManager).

**Verify:** start a job via POST, stream GET /api/manage/jobs/{id}/stream, receive log lines as SSE events, receive done event with exit code. Heartbeat comments arrive every 15s during idle periods.

### 11.6 Migrate tests

Replace from starlette.testclient import TestClient with from wesktop.testing import TestClient. Update conftest.py: test_client fixture creates wesktop TestClient with test database. Monkeypatch patterns for DB_PATH stay the same. DISABLE_RATELIMIT env var replaced with direct rate limiter disable in test config.

**Verify:** pytest passes with zero Starlette/FastAPI imports. All existing tests pass.

### 11.7 Wire desktop window

Add claudetimeline open command (or modify existing) to start server in background via wesktop.serve(foreground=False), then open pywebview native window with the dashboard. --browser flag for browser fallback.

**Verify:** claudetimeline open launches native window with CT dashboard. --browser opens browser tab.

### 11.8 Remove FastAPI/Starlette/uvicorn

Delete from pyproject.toml dependencies. Add wesktop. Grep and remove all imports.

**Verify:** clean pip install, all tests pass, grep finds no FastAPI/Starlette/uvicorn references.

---

## Phase 12: Frontend and desktop verification

Depends on Phases 9-11.

### 12.1 codehome dashboard smoke test

Start codehome server, open dashboard in browser. Test: login page, plugin list loads, SDUI rendering for telemac, SSE events (fire a test event via bus, verify dashboard updates), command palette, log viewer with ANSI colors.

**Verify:** all dashboard features render and function as before migration.

### 12.2 codehome desktop window test

Launch via codehome open (native window). Test: window opens at correct size, dashboard renders, login works, SSE updates arrive in real time, closing window shuts down server cleanly.

**Verify:** full user journey from open to close in native pywebview window.

### 12.3 CT dashboard smoke test

Start CT server, open dashboard in browser. Test: stats page loads with correct data, finder search works with filters, session list and detail pages, job streaming (start a job, watch SSE output in real time), bookmarks CRUD.

**Verify:** all CT features work as before migration.

### 12.4 CT desktop window test

Launch via claudetimeline open (native window). Same tests as 12.3 in native window.

**Verify:** full user journey in native pywebview window.

---

## Phase 13: Cleanup and finalization

### 13.1 Dependency cleanup

Both projects: verify pyproject.toml has no fastapi, starlette, or uvicorn. wesktop is listed as dependency. Run pip install -e . from clean venv for each project. Verify pip list shows no FastAPI.

**Verify:** fresh install succeeds for both projects without FastAPI in the dependency tree.

### 13.2 CI/CD verification

Both projects: ensure GitHub Actions publish workflows build wheels without FastAPI. wesktop available from PyPI (or installed from path during CI). NPM publish workflow for codehome's dashboard unchanged.

**Verify:** CI green on both repos (or dry-run confirms workflows would succeed).

### 13.3 Dead code sweep

Grep all three codebases (wesktop, codehome, CT) for lingering FastAPI references: "from fastapi", "from starlette", "import uvicorn", "Depends(", "APIRouter", "HTTPException", "BaseHTTPMiddleware", "response_model=". Remove any found.

**Verify:** zero grep hits for FastAPI/Starlette patterns across all three projects.

### 13.4 Plugin verification

Run a representative command from each of the 21 codehome plugins. Include: a plugin with dashboard routes (telemac), a plugin with checks (core), a plugin with cross-plugin services (lisa using supabase), a passthrough plugin (hubspot), a plugin with SDUI provider (telemac).

**Verify:** each plugin's core functionality works end-to-end through the CLI and dashboard.

---

## Dependency graph

Arrows mean "must complete before."

```
Phase 0 (groundwork)
  |
  v
Phase 1 (router foundations, including 1.10-1.14)
  |
  +---> Phase 2 (server lifecycle)        [parallel with 3-5]
  |
  +---> Phase 3 (DI + overrides) ---> Phase 4 (auth)  [sequential]
  |
  +---> Phase 5 (middleware/observability) [parallel with 3; 5.8 depends on 5.3]
  |
  +---> Phase 6 (Pydantic integration)    [parallel with 3]
  |
  v
Phase 7 (dev experience)                  [after 1, 4, 5]
  |
  v
Phase 8 (advanced features)               [after 6 for SDUI; rest after 1]
  |
  +---> Phase 9 (codehome core) ---> Phase 10 (plugins)  [sequential]
  |
  +---> Phase 11 (CT migration)                           [parallel with 9-10]
  |
  v
Phase 12 (frontend/desktop verification)   [after 9-11]
  |
  v
Phase 13 (cleanup)                         [after 12]
```

Phases 2, 3, 5, 6 can proceed in parallel after Phase 1 completes. Phase 4 depends on Phase 3. Phase 5.8 depends on Phase 5.3. Phases 9-10 and 11 can proceed in parallel after Phases 1-8 complete.

## Notes from internal review

Issues surfaced by consistency review, with resolution:

- **msgspec vs Pydantic**: No conflict. Pydantic validates and produces dicts, msgspec encodes dicts to JSON bytes. They serve different roles and coexist cleanly. The serialization boundary is documented in the resolved decisions table.
- **WebSocket route scoping**: Fixed in Phase 1.7 — WS routes are app-scoped, not module-level global.
- **Router composition**: Added Phase 1.10 — include_router with prefix and router-level dependencies.
- **Lifespan state + request.state**: Added Phase 1.11 — merging lifespan state into scope and adding Request.state property.
- **StreamResponse status code**: Added Phase 1.12 — status parameter for non-200 streaming responses.
- **DI test overrides**: Added Phase 3.4 — dependency_overrides dict for swapping deps in tests.
- **CSRF portability**: Documented in Phase 4.5 — scope["app"] replaced with middleware config, CLI token file stays in codehome.
- **Error response helper**: Added Phase 1.13 — send_error() for middleware, canonical ASGI type aliases.
- **Granian target string**: Resolved in Phase 2.1 — serve() accepts both string targets and callable app objects.
- **structlog context leak**: Phase 5.2 now clears contextvars at request start.
- **Error log hookup**: Phase 5.3 now describes 5xx escalation to error log.
- **Rate limiting mechanics**: Phase 4.7 now describes how the decorator extracts request, checks limit, and interacts with DI ordering.
- **Broadcaster heartbeat**: Noted in Phase 11.5 — CT needs heartbeat in SSE, Broadcaster could gain heartbeat_interval support.
- **create_app parameter explosion**: Acknowledged. 13+ parameters is the current reality. Will consider config object or builder pattern once the parameter set stabilizes post-migration.
- **query() coercion failure**: Phase 1.18 changes behavior — coercion failure raises 422 instead of silently returning default.
- **query_params property**: Added in Phase 1.18.

Second review additions:

- **No Response object for cookies**: Added Phase 1.14 — all response types gain optional headers dict and cookies list. Replaces FastAPI's mutable Response injection pattern.
- **Cookie extraction on Request**: Added Phase 1.15 — req.cookies property and req.cookie(name) method.
- **{key:path} path converter**: Added Phase 1.16 — greedy path matching for multi-segment parameters. Critical for codehome's services router.
- **FileResponse**: Added Phase 1.17 — file serving with proper Content-Length and MIME detection.
- **Plugin command dispatch introspection**: Noted in Phase 10.3 — SDUI command dispatch introspects FastAPI router internals and must be rewritten.
- **Sentry dep change**: Phase 5.7 now specifies sentry-sdk (no [fastapi] extra) and HTTPError filtering.
- **Granian asyncio.create_task**: Added Phase 0.2 — verify fire-and-forget tasks survive after handler returns.
- **request.json() sync vs async**: Noted in Phase 9.4 — await request.json() must become request.json (property).
- **Phase 9.4 verify step**: Changed from "existing tests adapted" to golden file contract testing.
- **Middleware constructor API**: Added Phase 1.19 — accept list[Callable] instead of list[type].
- **Overlapping prefix sub-routers**: Addressed by Phase 1.10 — include_router must handle multiple sub-routers at the same prefix with different auth requirements.

Third review additions:

- **State wrapper class**: Phase 1.11 now specifies a State wrapper (not raw dict) supporting both attribute assignment and dict access. Starlette's State does this; wesktop needs the same.
- **request.method, request.path**: Added to Phase 1.11 — convenience properties both consumers use pervasively.
- **request.is_disconnected()**: Added to Phase 1.11 — async method for SSE disconnect detection. Without it, heartbeat loops leak coroutines on dead connections.
- **delete_cookie**: Added to Phase 1.14 — convenience helper producing Set-Cookie with max_age=0.
- **parse_filters Query() pattern**: Phase 11.2 now explicitly addresses the rewrite from FastAPI Query() introspection to manual req.query() parsing.
- **CT handler count**: Corrected from 62 to ~69. Batch sizing updated. response_model migration (29 usages) added to Phase 11.3.
- **CT rate limiting behavioral change**: Noted in Phase 11.1 — global 120/minute drops to per-handler decoration.
- **CT pydantic dep chain**: Noted in Phase 11.1 — CT should add pydantic as explicit direct dep.
- **Phase numbering**: Fixed Phase 7.3 reference from 0.2 to 0.3.
- **Granian multi-worker concern**: Noted in Phase 2.1 — module-level app creation with side effects + multiple workers = repeated plugin loading.
- **CT timing middleware customization**: CT's observability middleware has custom behavior (route template access, query redaction, admin endpoint) beyond wesktop's built-in timing middleware. CT may need a custom middleware layer on top of wesktop's timing for these features.
