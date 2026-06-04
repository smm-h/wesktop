# Latent bug: granian SocketHolder fd not explicitly passed in spawn mode

## Bug

In Python's `spawn` multiprocessing mode, granian's `SocketHolder` (Rust/PyO3) is pickled via `copyreg` as just `(fd_number, is_uds, backlog)`. The fd number is embedded in the pickle payload but is NOT explicitly passed to the child process via `spawnv_passfds`.

It currently works only because `socket.socket` is also present in granian's worker args, and Python's `multiprocessing.reduction._reduce_socket` properly handles fd passing via `DupFd`. The `DupFd` mechanism ensures the socket fd is inherited by the child. When the child unpickles `SocketHolder`, the fd number happens to be valid because the same underlying socket was already passed through the proper channel.

If `self._sso` (the socket object) were ever removed from granian's worker args, the fd would not be passed in spawn mode. The `SocketHolder` unpickle would receive a stale fd number that doesn't exist in the child process.

## Current impact

None on Python 3.13 with fork mode (the default), because fork inherits all fds. This would break on Python 3.14+ where the default multiprocessing start method changes to forkserver/spawn on Linux.

## Proper fix

Register `SocketHolder` with `multiprocessing.reduction.register` instead of `copyreg.pickle`, using `DupFd` for explicit fd passing. This would make the fd inheritance explicit and correct regardless of the multiprocessing start method:

- The reduce function would use `multiprocessing.reduction.DupFd(self.fd)` to properly pass the fd to the child
- The reconstruct function would receive the inherited fd and build a new `SocketHolder` from it
- This removes the implicit dependency on `socket.socket` being present in the worker args
