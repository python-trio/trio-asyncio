# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import sys
import trio
import asyncio
import warnings
import threading
from contextvars import ContextVar

from async_generator import async_generator, yield_, asynccontextmanager

from ._util import run_aio_future, run_aio_generator
from ._async import TrioEventLoop
from ._deprecate import deprecated, warn_deprecated

try:
    from trio.hazmat import wait_for_child
except ImportError:
    from ._child import wait_for_child

# A substantial portion of the trio-asyncio test suite involves running the
# stock asyncio test suite with trio-asyncio imported. This is intended to
# test two things:
# - that trio-asyncio is a "good citizen": won't screw up other users of
#   asyncio if Trio isn't running
# - that trio-asyncio provides an event loop that conforms to asyncio semantics,
#   even if Trio is running
#
# It's hard to test both of these at once: in order to get good test
# coverage, we want normal asyncio calls to instantiate our loop, but
# the asyncio tests are full of tricky event loop manipulations, some
# of which expect to provide their own mock loop. We've compromised on
# the following.
#
# - The "actual" event loop policy (the one that would be returned by
#   an unpatched asyncio.get_event_loop_policy()) is set at import
#   time to a singleton instance of TrioPolicy, and never changed
#   later. This is required for correct operation in CPython 3.7+,
#   because the C _asyncio module caches the original
#   asyncio.get_event_loop_policy() and calls it from its accelerated
#   C get_event_loop() function. We want asyncio.get_event_loop() to be
#   able to return a trio-asyncio event loop.
#
# - To cope with tests that set a custom policy, we monkeypatch
#   asyncio.get_event_loop_policy() and set_event_loop_policy()
#   so that they model an event loop policy that is thread-local when
#   called outside of Trio context. Said policy is stored in at
#   _faked_policy.policy. (Inside Trio context, we let get_event_loop_policy()
#   return the singleton global TrioPolicy, and set_event_loop_policy()
#   raises an exception.)
#
#   - If you've previously called set_event_loop_policy() with a
#     non-None argument in the current thread, then
#     get_event_loop_policy() will return the thing that you passed to
#     set_event_loop_policy().
#
#   - If you haven't called set_event_loop_policy() in this thread
#     yet, or the most recent call in this context had a None
#     argument, then get_event_loop_policy() will return the asyncio
#     event loop policy that was installed when trio_asyncio was
#     imported.
#
# - Even though the user can set a per-thread policy and we'll echo it back,
#   the "actual" global policy is still the TrioPolicy and we don't expose
#   any way to change it. asyncio.get_event_loop() will use this TrioPolicy
#   on 3.7+ no matter what we do, so we monkeypatch new_event_loop() and
#   set_event_loop() to go through the TrioPolicy too (for consistency's sake)
#   and let TrioPolicy forward to the appropriate actual policy specified by
#   the user.
#
#   - Inside a Trio context, TrioPolicy refuses to create a new event loop
#     (you should use 'async with trio_asyncio.open_loop():' instead).
#     Its get/set event loop methods access a contextvar (current_loop),
#     which is normally set to the nearest enclosing open_loop() loop,
#     but can be modified if you want to put some Trio tasks in a
#     trio-asyncio event loop that doesn't correspond to their place in the
#     Trio task tree.
#
#   - Outside a Trio context when an event loop policy has been set,
#     TrioPolicy delegates all three methods (new/get/set event loop)
#     to that policy. Thus, if you install a custom policy, it will get
#     used (trio-asyncio gets out of the way).
#
#   - Outside a Trio context when no event loop policy has been set,
#     the get/set event loop methods manage a thread-local event loop
#     just like they do in default asyncio. However, new_event_loop() will
#     create a synchronous trio-asyncio event loop (the kind that can
#     be repeatedly started and stopped, which is helpful for many asyncio
#     tests). Thus, if you don't install a custom policy, tests that use
#     asyncio will exercise trio-asyncio.


class _FakedPolicy(threading.local):
    policy = None


_faked_policy = _FakedPolicy()


def _in_trio_context():
    try:
        trio.hazmat.current_task()
    except RuntimeError:
        return False
    else:
        return True


class _TrioPolicy(asyncio.events.BaseDefaultEventLoopPolicy):
    @staticmethod
    def _loop_factory():
        raise RuntimeError("Event loop creations shouldn't get here")

    def new_event_loop(self):
        if _in_trio_context():
            raise RuntimeError(
                "You're within a Trio environment.\n"
                "Use 'async with open_loop()' instead."
            )
        if _faked_policy.policy is not None:
            return _faked_policy.policy.new_event_loop()
        if 'pytest' not in sys.modules:
            warn_deprecated(
                "Using trio-asyncio outside of a Trio event loop",
                "0.10.0",
                issue=None,
                instead=None,
            )

        from ._sync import SyncTrioEventLoop
        return SyncTrioEventLoop()

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
            task = trio.hazmat.current_task()
        except RuntimeError:
            pass
        else:
            # Trio context. Note: NOT current_loop.get()! If this is called from
            # asyncio code, current_task() is the trio-asyncio loop runner task,
            # which has the correct loop set in its contextvar; but (on Python
            # 3.7+) our current context is quite possibly something different, and
            # might have the wrong contextvar value (e.g. in the case of a
            # loop1.call_later() in loop2's context).
            return task.context.get(current_loop)

        # Not Trio context
        if _faked_policy.policy is not None:
            return _faked_policy.policy.get_event_loop()

        # This will return the thread-specific event loop set using
        # set_event_loop(), or if none has been set, will call back into
        # our new_event_loop() to make a SyncTrioEventLoop and set it as
        # this thread's event loop.
        return super().get_event_loop()

    @property
    def current_event_loop(self):
        """The currently-running event loop, if one exists."""
        loop = current_loop.get()
        if loop is None:
            loop = super().get_event_loop()
        return loop

    def set_event_loop(self, loop):
        """Set the current event loop."""
        if _in_trio_context():
            current_loop.set(loop)
        elif _faked_policy.policy is not None:
            _faked_policy.policy.set_event_loop(loop)
        else:
            super().set_event_loop(loop)


from asyncio import events as _aio_event

#####


def _new_policy_get():
    if _in_trio_context():
        return _trio_policy
    elif _faked_policy.policy is not None:
        return _faked_policy.policy
    else:
        return _original_policy


def _new_policy_set(new_policy):
    if isinstance(new_policy, TrioPolicy):
        raise RuntimeError("You can't set the Trio loop policy manually")
    if _in_trio_context():
        raise RuntimeError("You can't change the event loop policy in Trio context")
    else:
        assert new_policy is None or isinstance(new_policy, asyncio.AbstractEventLoopPolicy)
        _faked_policy.policy = new_policy


_orig_policy_get = _aio_event.get_event_loop_policy
_orig_policy_set = _aio_event.set_event_loop_policy
_aio_event.get_event_loop_policy = _new_policy_get
_aio_event.set_event_loop_policy = _new_policy_set
asyncio.get_event_loop_policy = _new_policy_get
asyncio.set_event_loop_policy = _new_policy_set

#####

try:
    _orig_run_get = _aio_event._get_running_loop

except AttributeError:
    pass

else:

    def _new_run_get():
        try:
            task = trio.hazmat.current_task()
        except RuntimeError:
            pass
        else:
            # Trio context. Note: NOT current_loop.get()!
            # See comment in _TrioPolicy.get_event_loop().
            return task.context.get(current_loop)
        # Not Trio context
        return _orig_run_get()

    # Must override the non-underscore-prefixed get_running_loop() too,
    # else will use the C-accelerated one which doesn't call the patched
    # _get_running_loop()
    def _new_run_get_or_throw():
        result = _new_run_get()
        if result is None:
            raise RuntimeError("no running event loop")
        return result

    _aio_event._get_running_loop = _new_run_get
    _aio_event.get_running_loop = _new_run_get_or_throw

#####


def _new_loop_get():
    current_loop = _new_run_get()
    if current_loop is not None:
        return current_loop
    return _trio_policy.get_event_loop()


def _new_loop_set(new_loop):
    _trio_policy.set_event_loop(new_loop)


def _new_loop_new():
    return _trio_policy.new_event_loop()


_orig_loop_get = _aio_event.get_event_loop
_orig_loop_set = _aio_event.set_event_loop
_orig_loop_new = _aio_event.new_event_loop
_aio_event.get_event_loop = _new_loop_get
_aio_event.set_event_loop = _new_loop_set
_aio_event.new_event_loop = _new_loop_new
asyncio.get_event_loop = _new_loop_get
asyncio.set_event_loop = _new_loop_set
asyncio.new_event_loop = _new_loop_new

#####


class TrioPolicy(_TrioPolicy, asyncio.DefaultEventLoopPolicy):
    """This is the loop policy that's active whenever we're in a Trio context."""

    def _init_watcher(self):
        with asyncio.events._lock:
            if self._watcher is None:  # pragma: no branch
                self._watcher = TrioChildWatcher()
                if isinstance(threading.current_thread(), threading._MainThread):
                    self._watcher.attach_loop(current_loop.get())

        if self._watcher is not None and \
                isinstance(threading.current_thread(), threading._MainThread):
            self._watcher.attach_loop(current_loop.get())

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


_original_policy = _orig_policy_get()
_trio_policy = TrioPolicy()
_orig_policy_set(_trio_policy)

# Backwards compatibility -- unused
current_policy = ContextVar('trio_aio_policy', default=_trio_policy)

current_loop = ContextVar('trio_aio_loop', default=None)


class TrioChildWatcher(asyncio.AbstractChildWatcher if sys.platform != 'win32' else object):
    # AbstractChildWatcher not available under Windows
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


@asynccontextmanager
@async_generator
async def open_loop(queue_len=None):
    """Main entry point: run an asyncio loop on top of Trio.

    This is a context manager.

    Example usage::

            async def async_main(*args):
                async with trio_asyncio.open_loop() as loop:
                    pass
                    # async part of your main program here

    """

    # TODO: make sure that there is no asyncio loop already running

    def _main_loop_exit(self):
        super()._main_loop_exit()
        self._thread = None

    async with trio.open_nursery() as nursery:
        loop = TrioEventLoop(queue_len=queue_len)
        old_loop = current_loop.set(loop)
        try:
            loop._closed = False
            await loop._main_loop_init(nursery)
            await nursery.start(loop._main_loop)
            await yield_(loop)
        finally:
            try:
                await loop.stop().wait()
            finally:
                try:
                    await loop._main_loop_exit()
                finally:
                    loop.close()
                    nursery.cancel_scope.cancel()
                    current_loop.reset(old_loop)


def run(proc, *args, queue_len=None):
    """Like :func:`trio.run`, but adds a context that supports asyncio.
    """

    async def _run_task(proc, args):
        async with open_loop(queue_len=queue_len):
            return await proc(*args)

    return trio.run(_run_task, proc, args)


# Non-deprecated aliases for event loop methods


def _running_loop():
    loop = current_loop.get()
    if loop is None:
        raise RuntimeError("You are not within a trio_asyncio loop")
    return loop


async def run_aio_coroutine(fut):
    """Wait for an asyncio future/coroutine.

    Cancelling the current Trio scope will cancel the future/coroutine.

    Cancelling the future/coroutine will cause an
    ``asyncio.CancelledError``.

    This is a Trio coroutine.
    """
    return await _running_loop().run_aio_coroutine(fut)


def run_trio(proc, *args):
    """Call an asynchronous Trio function from asyncio.

    Returns a Future with the result / exception.

    Cancelling the future will cancel the Trio task running your
    function, or prevent it from starting if that is still possible.

    You need to handle errors yourself.
    """
    return _running_loop().run_trio(proc, *args)


def run_trio_task(proc, *args):
    """Call an asynchronous Trio function from sync context.

    This method queues the task and returns immediately.
    It does not return a value.

    An uncaught error will propagate to, and terminate, the trio-asyncio loop.
    """
    _running_loop().run_trio_task(proc, *args)


# These are aliases for methods in BaseTrioEventLoop which are
# themselves deprecated. If we deprecate these and call the deprecated
# loop method, the user gets two warnings. If we just call the
# deprecated loop method, the warning points here instead of to user
# code. Therefore, we "chase the pointer" and inline the body of the
# deprecated loop method into each of these functions.


@deprecated("0.10.0", issue=38, instead="aio_as_trio(proc(*args))")
def wrap_generator(proc, *args):
    return run_aio_generator(_running_loop(), proc(*args))


@deprecated("0.10.0", issue=38, instead="aio_as_trio(aiter)")
def run_iterator(aiter):
    return run_aio_generator(_running_loop(), aiter)


@deprecated("0.10.0", issue=38, instead="trio_as_aio(ctx)")
def wrap_trio_context(ctx):
    from ._adapter import Trio_Asyncio_Wrapper
    return Trio_Asyncio_Wrapper(ctx, loop=_running_loop())


@deprecated("0.10.0", issue=38, instead="aio_as_trio(proc)(*args)")
def run_asyncio(proc, *args):
    from ._adapter import Asyncio_Trio_Wrapper
    return Asyncio_Trio_Wrapper(proc, args=args, loop=_running_loop())


@deprecated("0.10.0", issue=38, instead="run_aio_coroutine")
async def run_coroutine(fut):
    return await _running_loop().run_aio_coroutine(fut)


@deprecated("0.10.0", issue=38, instead="run_aio_future")
async def run_future(fut):
    return await run_aio_future(fut)
