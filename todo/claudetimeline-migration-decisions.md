# Decisions for ClaudeTimeline migration to wesktop

ClaudeTimeline is the first real consumer migrating from FastAPI+uvicorn to wesktop. The migration surfaces 23 design decisions — many of which require extending wesktop. This file lists every decision, with options and tradeoffs, so they can be resolved before implementation begins.

## Context

ClaudeTimeline's server stack: 30 route modules, 62 handlers (52 GET, 9 POST, 2 DELETE), 85 Pydantic response models, 7 async handlers (manage.py jobs + SSE). Universal use of FastAPI's `Depends(get_conn)` and `Depends(parse_filters)`. `HTTPException` in 13 files. Custom middleware: CORS, TrustedHost, rate limiting, request logging. Server lifecycle via PID files, health probes, subprocess management.

---

## 1. Dependency injection

Affects all 62 route handlers. Currently every handler declares `conn=Depends(get_conn), filters=Depends(parse_filters)`.

Options:
- **Add DI to wesktop.** Handlers declare dependencies via annotations or decorators, framework resolves them per-request. Most correct — makes wesktop a real framework, benefits all future consumers. Significant effort.
- **Request-scoped middleware.** A wesktop ASGI middleware attaches shared objects (DB conn, parsed filters) to the request. Handlers access via `req.state.conn`. Low effort, decent ergonomics, but implicit — nothing enforces the middleware ran.
- **Explicit helper calls.** Each handler calls `get_conn(req)` and `parse_filters(req)` at the top. No framework support. Most transparent, but repetitive across 62 handlers.

## 2. Multi-value query parameter API

ClaudeTimeline sends `?account=a&account=b` and `?project=x,y`. wesktop's `Request.query()` returns only the first value.

Options:
- **Add `query_list(name)`** as a separate method returning all values. `query()` stays single-value.
- **Change `query()` to always return a list.** Breaking change to wesktop's existing API.
- **Add `query_all(name)` returning raw list + keep `query()` for single.** Same as option 1, different name.

## 3. Query parameter validation

FastAPI's `Query(ge=0, le=100)` validates at the framework level. wesktop has no validation.

Options:
- **Add validation to wesktop.** `req.query("limit", type_=int, ge=0, le=100)` with constraints. Makes wesktop more capable. Moderate effort.
- **Validate manually in handlers.** Consumer's responsibility. Keeps wesktop minimal.
- **Middleware-level validation via schemas.** Declare a param schema per route, middleware validates before handler runs. More structured but heavy.

## 4. Path parameter type coercion

wesktop path params are always strings. ClaudeTimeline uses `{cluster_id}`, `{session_id}`, `{job_id}` where some need int coercion.

Options:
- **Add `{id:int}` syntax** to route paths. Framework coerces and returns 400 on mismatch.
- **Leave as strings.** Handlers call `int(req.path_params["id"])` manually. Simple, but error handling is per-handler.

## 5. Body reading scope

wesktop reads request body only for POST. ClaudeTimeline has 2 DELETE routes (session deletion, project deletion) — need to verify whether they send a JSON body or use query/path params only.

Options:
- **Read body for all methods.** Simplest, no surprises.
- **Read for POST + PUT + PATCH + DELETE.** Covers all mutation methods.
- **Keep POST-only, verify DELETE routes don't need body.** Least change, but fragile if a future route needs it.

## 6. Error response format

wesktop returns `{"error": "..."}`. FastAPI returns `{"detail": "..."}`. The ClaudeTimeline frontend likely keys on `"detail"`.

Options:
- **`{"detail": "..."}`** — match FastAPI. Zero frontend changes. But it's a FastAPI-ism.
- **`{"error": "..."}`** — keep wesktop's format. Update frontend error handlers.
- **Configurable formatter.** HTTPError formats via a user-supplied function. ClaudeTimeline can emit `{"detail"}` during migration, switch later.

## 7. Custom exception handler registry

ClaudeTimeline registers handlers for `sqlite3.OperationalError` (-> 503) and a catch-all (-> 500 with traceback logging).

Options:
- **Add exception handler registry to wesktop.** `app.exception_handler(ExcType, handler_func)`. Flexible, matches FastAPI's pattern.
- **Only have HTTPError + single catch-all.** Consumers catch specific exceptions inside handlers or middleware. Simpler but pushes work to consumers.

## 8. External server stop

`wesktop.serve()` handles self-cleanup via signals and atexit. But ClaudeTimeline's CLI needs to stop a server from an external process (`serve stop` sends SIGTERM to the PID).

Options:
- **Add `wesktop.stop(pid_path)` utility.** Reads PID, sends SIGTERM, waits, escalates to SIGKILL. Symmetric with `serve()`.
- **Consumer handles it.** ClaudeTimeline keeps its own SIGTERM-sending code. Duplicates logic that wesktop already partially has.

## 9. External status/health introspection

The CLI needs `serve status` (is it running? is it healthy?). Currently `server_ctl.server_status()` reads PID file, checks liveness, probes `/api/health`.

Options:
- **Add `wesktop.status(pid_path, health_url)` utility.** Returns (running, pid, healthy). Pairs with `serve()` and `stop()`.
- **Consumer handles it.** ClaudeTimeline keeps its own status logic. wesktop stays server-only.

## 10. Reload / dev mode

Granian has no `--reload`. ClaudeTimeline's `dev` command runs `uvicorn --reload` alongside `vite dev`.

Options:
- **Add `serve(reload=True)` to wesktop.** Uses watchfiles to restart Granian on source changes. Most correct — every consumer benefits. Moderate effort.
- **Keep uvicorn as a dev-only dependency.** Production uses Granian. Dev uses uvicorn with `--reload`. Pragmatic but dev/prod diverge.
- **External watcher.** Use watchfiles CLI or a script. No framework change. Full process restart on every save — clunky.

## 11. Foreground mode API

`serve run` currently calls `uvicorn.run()` in-process, blocking, with optional `--reload`. `wesktop.serve()` also blocks.

Options:
- **`wesktop.serve()` gains a `foreground=True` option** (or it's always foreground, with a separate `serve_background()` for daemonizing). Reload support per decision 10.
- **Keep separate.** `wesktop.serve()` is always foreground. Background spawning is the consumer's job (subprocess + PID file). Current design.

## 12. Pre-serve hooks

ClaudeTimeline runs `npm run build` before starting if `frontend/dist/` is missing. 

Options:
- **Add a `pre_serve` callback to `wesktop.serve()`.** Called before Granian starts. Generic, useful for any consumer with a build step.
- **Consumer handles it.** Call the build logic before calling `serve()`. Simpler, keeps wesktop focused on serving.

## 13. Settings cascade (host/port from env vars)

`settings.py` resolves host/port via CLI flag > env var > default. `wesktop.serve()` accepts explicit host/port.

Options:
- **wesktop reads env vars itself.** `WESKTOP_HOST` / `WESKTOP_PORT` (or app-namespaced vars). Less boilerplate for consumers.
- **Consumer's responsibility.** Consumer reads env vars and passes to `serve()`. wesktop stays explicit-args-only.

## 14. Built-in CORS

Needed during development when Vite dev server (port 5173) is a different origin than the API.

Options:
- **Add CORS middleware to wesktop.** Useful for any consumer with a separate frontend dev server. Could be opt-in via `create_app(cors_origins=[...])`.
- **Consumer brings their own.** Use Starlette's `CORSMiddleware` or write a raw ASGI middleware. Keeps wesktop minimal but requires Starlette as a dependency.

## 15. Built-in request logging

wesktop currently logs nothing per-request.

Options:
- **Add basic request logging.** Method, path, status, latency — to Python logging. Opt-in via a flag. Useful for any consumer.
- **Consumer's responsibility.** Consumer writes their own logging middleware. Current approach.

## 16. TestClient

Tests currently use Starlette's `TestClient`. Removing FastAPI removes this.

Options:
- **Ship a TestClient in wesktop.** Wraps `httpx.AsyncClient` + `ASGITransport`. Lowers the barrier for testing wesktop apps.
- **Consumer wires up httpx themselves.** 3-4 lines of boilerplate. Keeps wesktop dependency-free from httpx.

## 17. Pydantic response models (85 models in models.py)

Used with FastAPI's `response_model=` for runtime response validation.

Options:
- **Drop entirely.** Delete models.py. Handlers return plain dicts. No runtime validation. Simplest migration. Type bugs in responses become silent. Acceptable for a local single-consumer app.
- **Keep for request validation only.** Delete the ~80 response models. Keep the ~5 request body models (BookmarkCreate, SavedViewCreate, etc.) validated manually via `Model.model_validate(req.json)`. Pydantic stays as a direct dep.
- **Add response_model to wesktop.** Route decorators gain a `response_model` parameter that validates/serializes. Most correct — keeps the safety net. Significant effort, makes wesktop opinionated about Pydantic.

## 18. Pydantic as a direct dependency

FastAPI brings Pydantic transitively. Without FastAPI, Pydantic must be explicitly depended on (for request body validation) or replaced.

Options:
- **Keep Pydantic as direct dep.** Used for request body validation in POST routes (annotations, manage). Clean, well-understood.
- **Replace with manual validation.** Parse `req.json` as dict, validate keys/types manually. No new dependency. More code, more error-prone.
- **Use msgspec for validation.** wesktop already uses msgspec internally for JSON. Could expose msgspec Structs for request validation. Tighter integration but different API from Pydantic.

## 19. Observability middleware

Custom `BaseHTTPMiddleware` subclass (Starlette) for request logging + slow-query ring buffer + `/api/admin/slow-queries`.

Options:
- **Port to raw ASGI middleware.** Remove Starlette dependency. More boilerplate but self-contained.
- **Keep as Starlette middleware.** Starlette stays as a direct dep just for this. Least effort but odd dependency for one file.
- **Merge into wesktop's built-in logging** (if decision 15 adds it). The slow-query ring buffer becomes a wesktop feature.

## 20. OpenAPI / docs endpoint

FastAPI auto-generates `/docs` (Swagger UI) and `/openapi.json`. These disappear with the migration.

Question: are `/docs` or `/openapi.json` used for anything? If not, this is a non-issue. If yes, need to decide whether wesktop should generate API docs.

## 21. `open` command default behavior

Currently `claudetimeline open` opens a browser tab. After migration, wesktop enables native desktop windows.

Options:
- **Default to native window.** `claudetimeline open` launches a native pywebview window. `--browser` flag falls back to browser. The full desktop app experience.
- **Default to browser.** Current behavior preserved. `--native` flag opts into the pywebview window. Safer default, pywebview may have rough edges.
- **Auto-detect.** If pywebview is importable, use native window. Otherwise, fall back to browser. Flexible but nondeterministic.

## 22. Migration order

Options:
- **Routes first.** Replace FastAPI routing with wesktop Router while keeping uvicorn. Validates the Router API early. Higher risk but delivers more value sooner.
- **Server first.** Replace uvicorn with Granian (wesktop.serve can serve the FastAPI ASGI app unchanged). Smaller step, validates Granian. Keeps FastAPI alive longer.

## 23. Starlette transitive dependency

Removing FastAPI removes Starlette. The observability middleware subclasses `BaseHTTPMiddleware` from Starlette.

Options:
- **Rewrite as raw ASGI middleware.** Clean break. More code.
- **Keep Starlette as direct dep.** Odd to depend on Starlette for one middleware class.
- **This resolves itself if decision 19 merges observability into wesktop's built-in logging.**

---

## Decision dependencies

Some decisions gate others:

- 1 (DI) affects how all 62 handlers are written — must decide before porting starts
- 2 (multi-value query) gates the filter parser — must decide before porting routes that use filters
- 6 (error format) gates frontend work — must decide before porting error-raising routes
- 10 (dev reload) gates the dev workflow — must decide before replacing the server lifecycle
- 17 (Pydantic models) + 18 (Pydantic dep) gate what models.py becomes — must decide before bulk route porting
- 7 (exception handlers) + 19 (observability) + 23 (Starlette dep) are coupled — observability's fate depends on whether wesktop gains exception handlers and/or built-in logging
