# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import sys
import trio
import asyncio
import warnings
import threading

from .util import run_future
from .async_ import TrioEventLoop, open_loop

try:
    from trio.hazmat import wait_for_child
except ImportError:
    from .child import wait_for_child

import logging
logger = logging.getLogger(__name__)

__all__ = [
    'run',
    'run_trio_task',
    'run_trio',
    'run_future',
    'run_coroutine',
    'run_asyncio',
    'TrioChildWatcher',
    'TrioPolicy',
]


class _TrioPolicy(asyncio.events.BaseDefaultEventLoopPolicy):
    _loop_factory = TrioEventLoop

    def __init__(self):
        super().__init__()
        self._trio_local = trio.RunLocal(_loop=None, _task=False)

    def new_event_loop(self):
        try:
            trio.hazmat.current_task()
        except RuntimeError:
            if 'pytest' not in sys.modules:
                warnings.warn(
                    "trio_asyncio should be used from within a Trio event loop.",
                    DeprecationWarning,
                    stacklevel=2
                )
            from .sync import SyncTrioEventLoop
            loop = SyncTrioEventLoop()
            return loop
        else:
            raise RuntimeError(
                "You're within a Trio environment.\n"
                "Use 'async with open_loop()' instead."
            )

    def get_event_loop(self):
        """Get the current event loop.

        Note that this will auto-generate an event loop if none exists, for
        compatibility with asyncio.

        To get a Trio-compatible asyncio loop, use
        ``async with trio_asyncio.open_loop() as loop:``.

        To test whether an event loop is running, check the loop policy's
        ``.current_event_loop`` property.
        """
        try:
            trio.hazmat.current_task()
        except RuntimeError:  # no Trio task is active
            # this creates a new loop in the main task
            return super().get_event_loop()
        else:
            return self._trio_local._loop

    @property
    def current_event_loop(self):
        """The currently-running event loop, if one exists."""
        try:
            return self._trio_local._loop
        except RuntimeError:
            # in the main thread this would create a new loop
            # return super().get_event_loop()
            return self._local._loop

    def set_event_loop(self, loop):
        """Set the current event loop."""
        try:
            task = trio.hazmat.current_task()
        except RuntimeError:
            return super().set_event_loop(loop)

        # This test will not trigger if you create a new asyncio event loop
        # in a sub-task, which is exactly what we intend to be possible
        if self._trio_local._loop is not None and loop is not None and \
                self._trio_local._task == task:
            raise RuntimeError('You cannot replace an event loop.')
        self._trio_local._loop = loop
        self._trio_local._task = task


class TrioPolicy(_TrioPolicy, asyncio.DefaultEventLoopPolicy):
    def _init_watcher(self):
        with asyncio.events._lock:
            if self._watcher is None:  # pragma: no branch
                self._watcher = TrioChildWatcher()
                if isinstance(threading.current_thread(), threading._MainThread):
                    self._watcher.attach_loop(self._trio_local._loop)

        if self._watcher is not None and \
                isinstance(threading.current_thread(), threading._MainThread):
            self._watcher.attach_loop(self._trio_local._loop)

    def set_child_watcher(self, watcher):
        if watcher is not None:
            if not isinstance(watcher, TrioChildWatcher):
                # raise RuntimeError("You must use a TrioChildWatcher here. "
                #                    "Sorry.")
                # warnings.warn("You must use a TrioChildWatcher.")
                #
                loop = watcher._loop  # ugh.
                watcher.close()
                watcher = TrioChildWatcher()
                watcher.attach_loop(loop)
        super().set_child_watcher(watcher)


class TrioChildWatcher(asyncio.AbstractChildWatcher):
    def __init__(self):
        super().__init__()
        self._callbacks = {}  # pid => handler

    def attach_loop(self, loop):
        self._loop = loop

    async def _waitpid(self, pid, callback, *args):
        returncode = await wait_for_child(pid)
        callback(pid, returncode, *args)

    def add_child_handler(self, pid, callback, *args):
        """Add a callback to run when a child process terminates."""
        h = self._loop.run_trio(self._waitpid, pid, callback, *args)
        self._callbacks[pid] = h

    def remove_child_handler(self, pid):
        """Remove the callback to run when a child process terminates."""
        h = self._callbacks.pop(pid, None)
        if h is None:
            return False
        h.cancel()
        return True

    def close(self):
        for pid in list(self._callbacks):
            h = self._callbacks.pop(pid, None)
            if h is None:
                continue
            h.cancel()
        self._loop = None

    def __enter__(self):
        return self

    def __exit__(self, *tb):
        self.close()


async def run_asyncio(proc, *args):
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return await loop.run_asyncio(proc, *args)


async def run_coroutine(fut, scope=None):
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return await loop.run_coroutine(fut, scope=scope)


def run_trio(proc, *args):
    """Call an asynchronous Trio function from asyncio.

    Returns a Future with the result / exception.

    Cancelling the future will cancel the Trio task running your
    function, or prevent it from starting if that is still possible.

    You need to handle errors yourself.
    """
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):  # pragma: no cover
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return loop.run_trio(proc, *args)


def run_trio_task(proc, *args):
    """Call an asynchronous Trio function from sync context.

    This method queues the task and returns immediately.
    It does not return a value.

    An uncaught error will propagate to, and terminate, the trio-asyncio loop.
    """
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    loop.run_trio_task(proc, *args)


def run(proc, *args, queue_len=None):
    """Like :func:`trio.run`, but adds a context that supports asyncio.
    """

    async def _run_task(proc, args):
        async with open_loop(queue_len=queue_len):
            return await proc(*args)

    trio.run(_run_task, proc, args)


asyncio.set_event_loop_policy(TrioPolicy())
