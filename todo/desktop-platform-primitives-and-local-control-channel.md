# Desktop platform primitives, a local control channel, and multi-window support

## Context

wesktop promises native windows on every platform pywebview supports:
WebKit on Linux and macOS, Edge WebView2 on Windows. The server layer,
the desktop-entry layer and the single-instance registry honour that. The
window layer does not yet: several operations a real desktop application
needs are missing from wesktop, so consumer apps reach past pywebview into
the GTK toplevel themselves (through the `_gtk_toplevel` helper pattern in
`desktop.py`), and on any other backend those calls silently do nothing.

A second gap is control. A wesktop app's ASGI server listens on loopback,
and any process on the machine can call any route. There is no framework
notion of "a command-line client talking to a running instance", only the
file-based focus-request marker used by `second_open="focus-existing"`.

This todo collects everything the window and control layers need before a
consumer can build a terminal-class application (many windows, long-lived
child processes, external CLI driving the running app) on wesktop without
platform-specific code of its own. It is one todo on purpose: the items
share the same two files and the same design rule, that every primitive
either works on each backend or refuses by name on the backends where it
cannot.

## Problems

### Window primitives reached through GTK by consumers

The following operations exist only as consumer-side GTK calls today.
Each needs a wesktop function with a GTK, a Cocoa and an Edge
implementation, or an explicit per-backend hard error naming the
operation and the backend:

- **Interactive resize from a page-drawn frame edge.** A frameless window
  has no OS handles. `begin_window_drag` exists for moves; the resize
  counterpart (`begin_window_resize(window, edge)`) does not.
- **Restore that really unmaximizes.** pywebview's GTK `restore()` only
  deiconifies. Consumers call the toplevel's unmaximize directly.
- **Minimize, maximize and a maximized-state query** as one consistent
  surface, so a page-drawn title bar can render the right button.
- **Clipboard read and write fallback** when the web view refuses
  `navigator.clipboard`. Consumers reach GDK for this; macOS needs
  NSPasteboard, Windows needs the Win32 clipboard.
- **Fullscreen toggle at runtime.** `WindowChrome.fullscreen` is a creation
  flag only.

### No focus or activation event

`runtime_bridge.py` documents that pywebview exposes no cross-platform
focus event and installs a poll instead. Any application that must know
which of its windows is active (to route a "new tab here" request, to
decide which window receives a notification click) needs a real event on
each backend, with the poll kept only where the backend has nothing.

### No close interception

pywebview raises a `closing` event whose handler can cancel the close.
wesktop does not surface it. Applications that host long-lived child
processes need to veto a close and show their own confirmation.

### No authenticated local control channel

An external process cannot safely tell a running wesktop app to do
anything. The loopback HTTP server is reachable by every local user
process with no authentication, so exposing "spawn", "close", or
"respawn" routes on it is not acceptable. Needed:

- A per-instance secret generated at start.
- A control transport with owner-only permissions: a unix socket on
  Linux and macOS, a named pipe on Windows.
- The secret and the transport address handed to child processes the app
  spawns (so a shell inside the app can talk back to it) and recorded in
  the instance registry (so a CLI can find the instance).
- Requests without the secret refused with a hard error; no fallback to
  the unauthenticated HTTP server.

### Instance discovery does not include how to reach an instance

`list_app_instances` and the pid file give a pid. A client also needs the
control-channel address of each instance, so "the instance that owns
resource X" is answerable.

### One window per process

`run()` sizes the process around one window. Terminal-class apps open
windows at runtime and need each window addressable (an id, its state,
its close hook) through the same control channel.

### Platform coverage of what already exists

- Theme following (`_appearance_portal`, `_install_theme_follow`) uses the
  Linux settings portal only. macOS needs NSAppearance observation,
  Windows the personalization registry key.
- `capture_window` is WebKitGTK-only.
- CI runs on Linux only, so the cross-platform claim is untested.

### Nice to have

- **Window state save and restore**: size, maximized and fullscreen state
  (position only where the platform allows reading it), keyed by app name,
  applied on next launch when the consumer opts in.
- **Desktop notifications** as one primitive, with a click action routed
  back to the app.

## Solutions

### A. Do all of it inside wesktop with per-backend implementations (recommended)

Add the primitives to `desktop.py` (or a new `window.py` if `desktop.py`
grows past readability), each dispatching on the detected pywebview
backend, with a hard error naming the backend where an operation is not
implemented yet. Add `control.py` for the authenticated channel and
extend the instance registry record with the channel address. Extend
`run()` to own a window list and expose window ids.

- Pros: one authority for platform behaviour; consumers delete their GTK
  code; the refusal-by-name rule makes unported backends visible instead
  of silent.
- Cons: three implementations per primitive; macOS and Windows work needs
  those machines or CI runners.

### B. Ship the Linux implementations now, refuse elsewhere

Same API, GTK implementation only, hard error on the other backends.

- Pros: consumers can drop their GTK code immediately; the API is fixed.
- Cons: the cross-platform promise stays unmet until the other backends
  are filled in.

### C. Leave primitives to consumers, add only the control channel

- Cons: every consumer re-implements the same GTK reach-through and none
  of them work off Linux.

## Affected files

- `src/wesktop/desktop.py`: `WindowChrome`, `_gtk_toplevel`,
  `begin_window_drag`, `_raise_window`, `_install_focus_request_poll`,
  `_appearance_portal`, `_install_theme_follow`, `capture_window`,
  `run`, `_run_window`, the instance registry helpers.
- `src/wesktop/runtime_bridge.py`: `install_focus_poll` and the note about
  the missing focus event.
- New `src/wesktop/control.py` (authenticated local channel) and the
  registry record format.
- `src/wesktop/cli.py`: diagnostics should report the control-channel
  address and the backend's primitive coverage.
- `docs/`: the platform-truth notes on `WindowChrome` and a new page for
  the control channel.
- Tests: fake-window tests for each primitive's dispatch and refusal, a
  control-channel test proving an unauthenticated request is refused.
- CI workflows: macOS and Windows runners for the backend-specific paths.

## Effort

Large. The control channel and the GTK implementations of the primitives
are a few days. The Cocoa and Edge implementations and CI are the long
tail and depend on access to those platforms.
