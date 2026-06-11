# serve(foreground=False) hangs in multithreaded processes

## Context

shopkeep's crawler test suite uses `wesktop.serve(foreground=False)` to start a mock shop server as a pytest fixture. These tests hang indefinitely during pre-push hooks, blocking releases. They are currently skipped with `pytest.mark.skip`.

The fixture in `crawler/tests/conftest.py` calls:
```python
wesktop.serve("tests.mock_shop.app:app", foreground=False, host="127.0.0.1", port=port, name="MOCK_SHOP_TEST")
```

## Three interacting bugs

### Bug 1: fork() in a multithreaded process

Granian's `MPServer` (used when `BUILD_GIL=True`, which is the default) spawns worker processes via `multiprocessing.Process` with `fork` or `spawn` start method. When `serve(foreground=False)` runs Granian in a daemon thread, the main process is already multithreaded (pytest's own threads, the daemon thread itself, Playwright browser threads). Calling `fork()` from a multithreaded process is undefined behavior per POSIX -- the child inherits only the calling thread, leaving mutexes in inconsistent states. This causes deadlocks in the worker processes.

The spawn method in `granian/server/mp.py` line 50-52 selects `fork` or `spawn` based on `multiprocessing.get_start_method()`. On Python 3.14, the default changed to `forkserver`, which Granian rejects and falls back to `spawn`. On older Pythons, it defaults to `fork`, which is the dangerous path.

### Bug 2: sys.exit(1) in daemon thread

Granian's `AbstractServer.shutdown()` (`granian/server/common.py` line 482-493) calls `sys.exit(exit_code)` when `exit_code` is non-zero. When Granian runs in a daemon thread (the `foreground=False` path), `sys.exit()` raises `SystemExit` which only terminates that thread, not the process. But the thread's cleanup may not complete properly, and any worker processes spawned by Granian become orphans -- there is no parent thread to reap them or forward signals.

Even on clean shutdown (exit_code=0), the daemon thread just silently returns from `server.serve()` with no notification to the caller. There is no event, callback, or any mechanism for the caller to know the server stopped.

### Bug 3: broken stop() API for daemon-thread servers

`wesktop.stop()` requires a `pid_path: Path` argument and works by sending SIGTERM to the PID written to that file. But `serve(foreground=False)` does not require or write a PID file (it runs in-process in a daemon thread, not as a subprocess). There is no API to stop a daemon-thread server.

The shopkeep conftest tries `wesktop.stop("MOCK_SHOP_TEST")` which passes a string where a Path is expected. Even if it were a valid Path, no PID file was written because `pid_path` was not passed to `serve()`. The teardown is a no-op -- the mock server is only cleaned up when the daemon thread dies with the process.

## Current mitigation in wesktop

The `foreground=False` path in `server.py` (lines 493-504) patches Granian's signal registration:
```python
_signals.set_main_signals = lambda *a, **kw: None
_granian_common.set_main_signals = lambda *a, **kw: None
```
This prevents the `ValueError: signal only works in main thread` crash but does not address:
- Worker process forking in a multithreaded process (Bug 1)
- sys.exit() in shutdown only killing the thread (Bug 2)
- No shutdown mechanism for daemon-thread servers (Bug 3)

The noop also means Granian's interrupt signal handler never runs, so `signal_handler_interrupt` is never called, `interrupt_signal` is never set, and `_serve_loop` blocks on `main_loop_interrupt.wait()` forever -- the server thread cannot be stopped.

## Suggested fix

Two approaches, not mutually exclusive:

### Option A: Use subprocess for background mode (recommended)

`serve_background()` already exists and uses `subprocess.Popen` with `start_new_session=True`. The `foreground=False` path in `serve()` should be changed to also use a subprocess instead of a daemon thread. This avoids all three bugs:
- No fork-in-multithreaded-process (the subprocess is single-threaded at startup)
- No sys.exit-in-daemon-thread (shutdown happens via SIGTERM to the subprocess)
- stop() works via PID file (the subprocess writes one)

The `serve_background()` function already demonstrates this pattern but spawns a fully detached process. `serve(foreground=False)` could spawn a child process that dies when the parent exits (not fully detached), which is the expected lifecycle for a test fixture server.

### Option B: Event-based shutdown for in-process daemon thread

If in-process daemon thread mode is worth keeping (e.g., for lower overhead in test fixtures):
1. Pass a `threading.Event` into the daemon thread
2. Instead of relying on signal handlers, have the server poll the event in `_serve_loop`
3. Expose a `stop_event.set()` method on the return value of `serve(foreground=False)`
4. Do not use Granian's `MPServer` (fork) in daemon-thread mode -- use `MTServer` (threading) or configure `spawn` start method explicitly
5. Monkey-patch `shutdown()` to not call `sys.exit()` when running in a thread

This is more complex and requires careful Granian integration, but avoids subprocess overhead.

## Impact

- shopkeep: 11 browser/integration tests permanently skipped, blocking test coverage of the crawl pipeline
- Any wesktop consumer using `serve(foreground=False)` in a multithreaded context will hit hangs
