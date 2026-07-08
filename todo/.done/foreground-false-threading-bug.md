# foreground=False threading bug: signal only works in main thread

## Bug

`wesktop.serve(foreground=False)` spawns granian in a daemon thread, but granian's `set_main_signals()` requires the main thread. This causes:

```
ValueError: signal only works in main thread of the main interpreter
```

## Where discovered

shopkeep's `sk dev` command tried to launch two backends in one process using `foreground=False` for the first backend and `foreground=True` for the second. The first backend crashed immediately with the signal error because the daemon thread cannot register signal handlers.

## Workaround used

shopkeep launches each backend as a separate subprocess instead of using `foreground=False`. This avoids the threading issue entirely but means `foreground=False` remains broken for any caller that wants to run multiple servers in one process.

## Affected code

`wesktop/src/wesktop/server.py` around line 277 where the daemon thread is created for background mode.

## Fix options

1. **Use subprocess.Popen instead of threading.Thread for background mode.** Instead of spawning granian in a daemon thread within the same process, launch it as a child subprocess. This sidesteps the signal issue because each subprocess has its own main thread. This is the more correct fix -- background mode should mean "run in the background" not "run in a thread."

2. **Catch the signal error in granian and skip signal setup when not in the main thread.** Granian could detect that it's not running in the main thread and skip `set_main_signals()`. This is a granian-side fix and would make granian thread-safe, but it means granian running in a thread would not handle signals (SIGTERM, SIGINT) -- the caller would be responsible for shutdown.
