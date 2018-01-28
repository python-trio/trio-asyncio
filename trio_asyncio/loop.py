# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import sys
import trio
import asyncio
import math
import heapq
import signal
import threading
import selectors
import traceback

import logging
logger = logging.getLogger(__name__)

from functools import partial
from asyncio.events import _format_callback, _get_function_source
from selectors import _BaseSelectorImpl, EVENT_READ, EVENT_WRITE

from async_generator import async_generator, yield_, asynccontextmanager
from .util import run_future

__all__ = ['open_loop', 'run_trio','run_future','run_coroutine','run_asyncio']


class _Clear:
    def clear(self):
        pass


def _format_callback_source(func, args):
    func_repr = _format_callback(func, args, None)
    source = _get_function_source(func)
    if source:  # pragma: no cover
        func_repr += ' at %s:%s' % source
    return func_repr


class _TrioHandle:
    """
    This extends asyncio.Handle by providing:
    * a way to pass keyword arguments
    * a way to cancel an async callback
    * a way to declare the type of the callback function
    
    ``is_sync`` may be
    * True: sync function, use _call_sync()
    * False: async function, use _call_async()
    * None: also async, but the callback function accepts
      the handle as its sole argument

    The caller is responsible for checking whether the handle
    has been cancelled before invoking ``call_[a]sync()``.
    """

    def _init(self, is_sync):
        """Secondary init.
        """
        self._is_sync = is_sync
        self._scope = None

    def cancel(self):
        super().cancel()
        if self._scope is not None:
            self._scope.cancel()

    def _cb_future_cancel(self, f):
        """If a Trio task completes an asyncio Future,
        add this callback to the future
        and set ``_scope`` to the Trio cancel scope
        so that the task is terminated when the future gets canceled.

        """
        if f.cancelled():
            self.cancel()

    def _repr_info(self):
        info = [self.__class__.__name__]
        if self._cancelled:
            info.append('cancelled')
        if self._callback is not None:
            info.append(
                _format_callback_source(
                    self._callback, self._args
                )
            )
        if self._source_traceback:
            frame = self._source_traceback[-1]
            info.append('created at %s:%s' % (frame[0], frame[1]))
        return info

    def _call_sync(self):
        assert self._is_sync
        if self._cancelled:
            return
        res = self._callback(*self._args)
        return res

    async def _call_async(self, task_status=trio.TASK_STATUS_IGNORED):
        assert not self._is_sync
        if self._cancelled:
            return
        task_status.started()
        try:
            with trio.open_cancel_scope() as scope:
                self._scope = scope
                if self._is_sync is None:
                    res = await self._callback(self)
                else:
                    res = await self._callback(*self._args)
            return res
        finally:
            self._scope = None


class Handle(_TrioHandle, asyncio.Handle):
    def __init__(self, callback, args, loop, is_sync):
        super().__init__(callback, args, loop)
        self._init(is_sync)


class TimerHandle(_TrioHandle, asyncio.TimerHandle):
    def __init__(self, when, callback, args, loop, is_sync):
        super().__init__(when, callback, args, loop)
        self._init(is_sync)


class _TrioSelector(_BaseSelectorImpl):
    """A selector that hooks into a ``TrioEventLoop``.

    In fact it's just a basic selector that disables the actual
    ``select()`` method, as that is controlled by the event loop.
    """

    def select(self, timeout=None):  # pragma: no cover
        raise NotImplementedError

    def _select(self, r, w, x, timeout=None):  # pragma: no cover
        raise NotImplementedError


class TrioExecutor:
    """An executor that runs its job in a Trio worker thread."""
    def __init__(self, limiter=None):
        self._running = True
        self._limiter = limiter

    async def submit(self, func, *args):
        if not self._running:  # pragma: no cover
            raise RuntimeError("Executor is down")
        return await trio.run_sync_in_worker_thread(
            func, *args, limiter=self._limiter
        )

    def shutdown(self, wait=None):
        self._running = False


class TrioEventLoop(asyncio.SelectorEventLoop):
    """An asyncio mainloop for trio.

    This code implements a semi-efficient way to run asyncio code within Trio.
    """
    # for calls from other threads
    _token = None

    # to propagate exceptions raised in the main loop
    _exc = None

    # Set by .stop() to an event; triggered when actually stopped
    _stopped = None

    # required by asyncio
    _closed = False

    def __init__(self, nursery):
        # Processing queue
        self._q = trio.Queue(9999)

        # Nursery
        self._nursery = nursery

        # which files to close?
        self._close_files = set()

        # set up
        super().__init__(_TrioSelector())

        # replaced internal data
        self._ready = _Clear()
        self._scheduled = _Clear()
        self._default_executor = TrioExecutor()

        self._orig_signals = {}

        # we do our own timeout handling
        self._timers = []

    def time(self):
        """Use Trio's idea of the current time.
        """
        return trio.current_time()

    # A future doesn't require a trio_asyncio loop
    run_future = staticmethod(run_future)

    # A coroutine (usually) does.
    async def run_coroutine(self, coro):
        """Wait for an asyncio future/coroutine from Trio code.

        Cancelling the current Trio scope will cancel the future/coroutine.

        Cancelling the future/coroutine will cause an ``asyncio.CancelledError``.
        """
        self._check_closed()
        return await run_future(coro)

    async def run_asyncio(self, proc, *args):
        """Call an asyncio function or method from Trio.
        
        Returns/Raises: whatever the procedure does.

        @scope: see ``run_future``.
        """
        f = asyncio.ensure_future(proc(*args), loop=self)
        return await self.run_coroutine(f)

    def run_trio(self, proc, *args):
        """Call an asynchronous Trio function from asyncio.

        Returns a Future with the result / exception.

        Cancelling the future will cancel the Trio task running your
        function, or prevent it from starting if that is still possible.

        You need to handle errors yourself.
        """
        self._check_closed()
        f = asyncio.Future(loop=self)
        h = Handle(self.__run_trio, (
            f,
            proc,
        ) + args, self, None)
        self._queue_handle(h)
        f.add_done_callback(h._cb_future_cancel)
        return f

    def run_trio_task(self, proc, *args):
        """Call an asynchronous Trio function from asyncio.

        This method starts the task in the background and returns immediately.
        It does not return a value.

        An uncaught error will propagate to, and terminate, the trio-asyncio loop.
        """
        self._nursery.start_soon(proc, *args)

    async def __run_trio(self, h):
        """Helper for copying the result of a task to a future"""
        f, proc, *args = h._args
        if f.cancelled():  # pragma: no cover
            return
        try:
            with trio.open_cancel_scope() as scope:
                h._scope = scope
                res = await proc(*args)
            if scope.cancelled_caught:
                f.cancel()
                return
        except Exception as exc:
            if not f.cancelled():  # pragma: no branch
                f.set_exception(exc)
        else:
            if not f.cancelled():  # pragma: no branch
                f.set_result(res)

    def call_later(self, delay, callback, *args):
        """asyncio's timer-based delay

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_later')
        self._check_closed()
        assert delay >= 0, delay
        h = TimerHandle(delay + self.time(), callback, args, self, True)
        self._q.put_nowait(h)
        return h

    def _queue_handle(self, handle):
        self._q.put_nowait(handle)
        return handle

    def call_at(self, when, callback, *args):
        """asyncio's time-based delay

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_at')
        self._check_closed()
        return self._queue_handle(
            TimerHandle(when, callback, args, self, True)
        )

    def call_soon(self, callback, *args):
        """asyncio's defer-to-mainloop

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_soon')
        self._check_closed()
        return self._queue_handle(Handle(callback, args, self, True))

    def call_soon_threadsafe(self, callback, *args):
        """asyncio's thread-safe defer-to-mainloop

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_soon_threadsafe')
        self._check_closed()
        h = Handle(callback, args, self, True)
        self._token.run_sync_soon(self._q.put_nowait, h)

    # supersede some built-ins which should not be used

    def _add_callback(self, handle, _via_token=False):
        raise RuntimeError("_add_callback() should have been superseded")

    def _add_callback_signalsafe(self, handle):  # pragma: no cover
        raise RuntimeError("_add_callback_signalsafe() should have been superseded")

    def _handle_signal(self, signum):
        raise RuntimeError("_handle_signal() should have been superseded")

    def _timer_handle_cancelled(self, handle):
        pass

    def run_in_executor(self, executor, func, *args):
        """
        Delegate running a synchronous function to another thread.

        Limitation:
        The executor must be None, or a (subclass of) ``TrioExecutor``.

        Returns an asyncio.Future.
        """
        self._check_callback(func, 'run_in_executor')
        self._check_closed()
        if executor is None: # pragma: no branch
            executor = self._default_executor
        assert isinstance(executor, TrioExecutor)
        return self.run_trio(executor.submit, func, *args)

    def _handle_sig(self, sig, _):
        h = self._signal_handlers[sig]
        self._token.run_sync_soon(self._q.put_nowait, h)

    async def _sync(self):
        w = trio.Event()
        self._q.put_nowait(w)
        await w.wait()

    def add_signal_handler(self, sig, callback, *args):
        self._check_signal(sig)
        self._check_closed()
        if sig == signal.SIGKILL:
            raise RuntimeError("SIGKILL cannot be caught")
        h = Handle(callback, args, self, True)
        assert sig not in self._signal_handlers, \
            "Signal %d is already caught" % (sig,)
        self._orig_signals[sig] = signal.signal(sig, self._handle_sig)
        self._signal_handlers[sig] = h

    def remove_signal_handler(self, sig):
        self._check_signal(sig)
        try:
            h = self._signal_handlers.pop(sig)
        except KeyError:
            return False
        h.cancel()
        signal.signal(sig, self._orig_signals[sig])
        del self._orig_signals[sig]
        return True

    def add_reader(self, fd, callback, *args):
        self._ensure_fd_no_transport(fd)
        return self._add_reader(fd, callback, *args)

    def _add_reader(self, fd, callback, *args):
        self._check_closed()
        handle = Handle(callback, args, self, True)
        reader = self._set_read_handle(fd, handle)
        if reader is not None:
            reader.cancel()
        if self._token is None:
            return
        self._nursery.start_soon(self._reader_loop, fd, handle)

    def _set_read_handle(self, fd, handle):
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, EVENT_READ, (handle, None))
            return None
        else:
            mask, (reader, writer) = key.events, key.data
            self._selector.modify(fd, mask | EVENT_READ, (handle, writer))
            return reader

    async def _reader_loop(self, fd, handle, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        with trio.open_cancel_scope() as scope:
            handle._scope = scope
            try:
                while not handle._cancelled:  # pragma: no branch
                    await trio.hazmat.wait_readable(fd)
                    handle._call_sync()
                    await self._sync()
            finally:
                handle._scope = None

    # writing to a file descriptor

    def add_writer(self, fd, callback, *args):
        self._ensure_fd_no_transport(fd)
        return self._add_writer(fd, callback, *args)

    def _add_writer(self, fd, callback, *args):
        self._check_closed()
        handle = Handle(callback, args, self, True)
        writer = self._set_write_handle(fd, handle)
        if writer is not None:
            writer.cancel()
        if self._token is None:
            return
        self._nursery.start_soon(self._writer_loop, fd, handle)

    def _set_write_handle(self, fd, handle):
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, EVENT_WRITE, (None, handle))
        else:
            mask, (reader, writer) = key.events, key.data
            self._selector.modify(fd, mask | EVENT_WRITE, (reader, handle))
            return writer

    async def _writer_loop(self, fd, handle, task_status=trio.TASK_STATUS_IGNORED):
        with trio.open_cancel_scope() as scope:
            handle._scope = scope
            task_status.started()
            try:
                while not handle._cancelled:  # pragma: no branch
                    await trio.hazmat.wait_writable(fd)
                    handle._call_sync()
                    await self._sync()
            finally:
                handle._scope = None

    def _cancel_fds(self):
        map = self._selector.get_map()
        for fd, key in list(self._selector.get_map().items()):
            for flag in (0, 1):
                if key.events & (1 << flag):
                    handle = key.data[flag]
                    assert handle is not None
                    if not handle._cancelled:  # pragma: no branch
                        if handle._scope is not None:
                            handle._scope.cancel()

    def _cancel_timers(self):
        for tm in self._timers:
            tm.cancel()
        self._timers.clear()

    # Trio-based main loop

    async def _main_loop(self, task_status=trio.TASK_STATUS_IGNORED):
        """This is the Trio replacement of the asyncio loop's main loop.

        Do not call this directly; use ``async with trio_asyncio.open_loop()`` instead.
        """
        self._stopping = False
        self._stopped = trio.Event()

        try:
            self._task = trio.hazmat.current_task()
            self._token = trio.hazmat.current_trio_token()

            task_status.started()

            while True:
                obj = None
                if self._timers:
                    timeout = self._timers[0]._when - self.time()
                    if timeout <= 0:
                        obj = heapq.heappop(self._timers)
                else:
                    timeout = math.inf

                if obj is None:
                    with trio.move_on_after(timeout) as cancel_scope:
                        obj = await self._q.get()
                    if cancel_scope.cancel_called:
                        continue

                    if isinstance(obj, trio.Event):
                        if obj is self._stopped:
                            break
                        obj.set()
                        continue
                    if isinstance(obj, TimerHandle):
                        heapq.heappush(self._timers, obj)
                        continue
                if obj._cancelled: # simply skip cancelled handlers
                    continue

                # Don't go through the expensive nursery dance
                # if this is a sync function anyway.
                if getattr(obj, '_is_sync', True):
                    obj._callback(*obj._args)
                else:
                    await self._nursery.start(obj._call_async)

        finally:
            self._stopping = True # it's false if there was an error

            # Kill off open work
            self._cancel_fds()
            self._cancel_timers()

            self._nursery = None
            self._task = None

            self._stopped.set()
            self.close()



    def run_forever(self):
        """You cannot call into trio_asyncio from a non-async context.
        Use 'await loop.wait_stopped()' instead.
        """
        raise RuntimeError("replace with 'await loop.wait_stopped()'")

    def run_until_complete(self, *x):
        """You cannot call into trio_asyncio from a non-async context.
        Use 'await loop.run_asyncio()' instead.
        """
        raise RuntimeError("replace with 'await loop.run_asyncio(...)'")
        
    async def wait_stopped(self):
        await self._stopped.wait()
    wait_closed = wait_stopped #possible  TODO

    def stop(self):
        """Halt the main loop.

        This returns a trio.Event which will trigger when the loop has
        terminated.
        """
        if not self._stopping:
            self._stopping = True
            self._queue_handle(self._stopped)

        return self._stopped

    def is_running(self):
        return self._stopped is not None and not self._stopped.is_set()

    def close(self):
        forgot_stop = self.is_running()
        if forgot_stop:
            raise RuntimeError("You need to stop the loop before closing it")

        super().close()

    def __aenter__():
        raise RuntimeError("You need to use 'async with open_loop()'.")

    def __aexit__(a,b,c):
        raise RuntimeError("You need to use 'async with open_loop()'.")

    def __enter__():
        raise RuntimeError("You need to use 'async with'.")

    def __exit__(a,b,c):
        raise RuntimeError("You need to use 'async with'.")

class _TrioPolicy(asyncio.events.BaseDefaultEventLoopPolicy):
    _loop_factory = TrioEventLoop

    def __init__(self):
        self._local = trio.TaskLocal(_loop=None, _task=False)

    def get_event_loop(self):
        """Get the current event loop.

        Note that this cannot autogenerate an event loop.
        Always use "with trio_asyncio.open_loop() as loop".
        """
        return self._local._loop

    def set_event_loop(self, loop):
        """Set the current event loop.
        
        Note that you cannot replace the running event loop.
        """
        task = trio.hazmat.current_task()
        if self._local._loop is not None and loop is not None and \
            self._local._task == task:
            raise RuntimeError('You cannot replace an event loop.')
        self._local._loop = loop
        self._local._task = task

class TrioPolicy(_TrioPolicy, asyncio.DefaultEventLoopPolicy):
    pass

@asynccontextmanager
@async_generator
async def open_loop():
    async with trio.open_nursery() as nursery:
        loop = TrioEventLoop(nursery)
        try:
            asyncio.set_event_loop(loop)
            await nursery.start(loop._main_loop)
            await yield_(loop)
        finally:
            try:
                await loop.stop().wait()
            finally:
                asyncio.set_event_loop(None)
                loop.close()

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
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return loop.run_trio(proc, *args)

def run_trio_task(proc, *args):
    """Call an asynchronous Trio function from asyncio.

    This method starts the task in the background and returns immediately.
    It does not return a value.

    An uncaught error will propagate to, and terminate, the trio-asyncio loop.
    """
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    loop.run_trio_task(proc, *args)

asyncio.set_event_loop_policy(TrioPolicy())
