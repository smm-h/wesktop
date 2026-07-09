# StreamResponse: detect client disconnect and close the generator

## Context

`StreamResponse` drives an async generator from `_send_stream` in `asgi.py` (~lines 873-886): it sends `http.response.start`, then loops `async for chunk in resp.generator` calling `send()` per chunk. Under granian, when the client disconnects mid-stream, subsequent `send()` calls do not raise into Python — granian swallows the failure and logs `[INFO] ASGI transport error: SendError { .. }` — and nothing ever cancels the coroutine.

## Problem

A long-lived streaming handler (e.g., an SSE endpoint blocking on a queue between sends) never learns the client is gone:

- The generator keeps running forever (or until it happens to yield, and even then the failed send does not stop it).
- Its `finally` blocks never run, so any resources held across yields — database connections, LISTEN registrations, file handles — leak permanently, once per abandoned client connection.
- The only trace is the swallowed INFO line, one per failed send.

The ASGI spec provides the disconnect signal: `receive()` yields `{"type": "http.disconnect"}` when the client goes away. `_send_stream` never awaits `receive()`, so the signal is invisible.

## Solutions

1. **Framework-level disconnect watcher (most correct).** In `_send_stream`, race the generator-driving loop against a watcher task that awaits `receive()` until `http.disconnect`. On disconnect: `await resp.generator.aclose()` (raises `GeneratorExit` at the yield point so handler `finally` blocks run), cancel the watcher on normal completion, handle the both-finish race. This is the pattern Starlette uses (`StreamingResponse` + `listen_for_disconnect`).
   - Pros: fixes every streaming consumer at once; no handler changes; resource cleanup guaranteed.
   - Cons: task-group bookkeeping in the hot path; needs careful tests for the completion/disconnect race and for servers that emit `http.disconnect` late.
2. **Expose `request.is_disconnected()` for handlers to poll.**
   - Pros: trivial to implement.
   - Cons: opt-in — every streaming handler must remember to poll; blocked handlers (waiting on a queue) still never notice; does not fix existing consumers.
3. **Both**: (1) for correctness, (2) as an escape hatch for handlers that want early exit before an expensive chunk.

Option 1 is the correct fix; option 2 alone does not solve the leak for handlers blocked between yields.

## Affected files

- `asgi.py`: `_send_stream` and the dispatch path that owns `receive`.
- Tests: red-green — a streaming handler with a `finally` that records cleanup; simulate a client disconnect (`receive` returning `http.disconnect`) while the generator is blocked between yields; assert `finally` ran and the response loop exited. Also test normal completion still works and the watcher task is cancelled.
- Docs for `StreamResponse` semantics.

## Effort

Roughly half a day including the race-condition tests.
