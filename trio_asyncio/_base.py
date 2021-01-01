import os
import sys
import math
import trio
import heapq
import signal
import sniffio
import asyncio
import warnings
import concurrent.futures

from ._handles import ScopedHandle, AsyncHandle
from ._util import run_aio_future

from selectors import _BaseSelectorImpl, EVENT_READ, EVENT_WRITE

try:
    from trio.lowlevel import wait_for_child
except ImportError:
    from ._child import wait_for_child

import logging
logger = logging.getLogger(__name__)

_mswindows = (sys.platform == "win32")

try:
    _wait_readable = trio.lowlevel.wait_readable
    _wait_writable = trio.lowlevel.wait_writable
except AttributeError:
    _wait_readable = trio.lowlevel.wait_socket_readable
    _wait_writable = trio.lowlevel.wait_socket_writable


class _Clear:
    def clear(self):
        pass


class _TrioSelector(_BaseSelectorImpl):
    """A selector that hooks into a ``TrioEventLoop``.

    In fact it's just a basic selector that disables the actual
    ``select()`` method, as that is controlled by the event loop.
    """

    def select(self, timeout=None):  # pragma: no cover
        raise NotImplementedError

    def _select(self, r, w, x, timeout=None):  # pragma: no cover
        raise NotImplementedError


class TrioExecutor(concurrent.futures.ThreadPoolExecutor):
    """An executor that runs its job in a Trio worker thread.

    Bases: `concurrent.futures.ThreadPoolExecutor`

    Arguments:
      limiter (trio.CapacityLimiter or None): If specified, use this
          capacity limiter to control the number of threads in which
          this exeuctor can be running jobs.
      thread_name_prefix: unused
      max_workers (int or None): If specified and *limiter* is not specified,
          create a new `trio.CapacityLimiter` with this value as its limit,
          and use that as the *limiter*.

    """

    def __init__(self, limiter=None, thread_name_prefix=None, max_workers=None):
        self._running = True
        if limiter is None and max_workers is not None:
            limiter = trio.CapacityLimiter(max_workers)
        self._limiter = limiter

    async def submit(self, func, *args):
        if not self._running:  # pragma: no cover
            raise RuntimeError("Executor is down")
        lim = self._limiter
        if lim is not None:
            await lim.acquire()
        try:
            return await trio.to_thread.run_sync(func, *args, limiter=self._limiter)
        finally:
            if lim is not None:
                lim.release()

    def shutdown(self, wait=None):
        self._running = False


class BaseTrioEventLoop(asyncio.SelectorEventLoop):
    """An asyncio event loop that runs on top of Trio.

    Bases: `asyncio.SelectorEventLoop`

    All event loops created by trio-asyncio are of a type derived from
    `BaseTrioEventLoop`.

    Arguments:
        queue_len:
            The maximum length of the internal event queue.
            The default is 1000. Use more for large programs,
            or when running benchmarks.
    """

    # This code implements a semi-efficient way to run asyncio code within Trio.
    # A loop may be in one of four states.
    #
    # * new - sync loops are auto-started when first used
    # * stopped - data structures are live but the main loop is not running
    # * running - events are processed
    # * closed - nothing further may happen

    # for calls from other threads or contexts
    _token = None

    # an event; set while the loop is not running
    # To wait until the loop _is_ running, call ``await loop.synchronize()``.
    _stopped = None

    # asyncio's flag whether the loop has been closed
    _closed = False

    # All sub-tasks are started in here
    _nursery = None

    # (Trio) task this loop is running in
    _task = None

    # (threading) Thread this loop is running in
    _thread = None

    def __init__(self, queue_len=None):
        if queue_len is None:
            queue_len = 10000

        # Processing queue
        self._q_send, self._q_recv = trio.open_memory_channel(queue_len)

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

        # Marker whether the loop is actually running
        self._stopped = trio.Event()
        self._stopped.set()

        self._stop_wait = None

    def __repr__(self):
        try:
            return "<%s running=%s at 0x%x>" % (
                self.__class__.__name__, "closed" if self._closed else "no"
                if self._stopped.is_set() else "yes", id(self)
            )
        except Exception as exc:
            return "<%s ?:%s>" % (self.__class__.__name__, repr(exc))

    def set_default_executor(self, executor):
        if not isinstance(executor, TrioExecutor):
            if 'pytest' not in sys.modules:
                warnings.warn(
                    "executor %r is not supported by trio-asyncio and will "
                    "not be used" % (repr(executor),),
                    RuntimeWarning,
                    stacklevel=2
                )
            return
        super().set_default_executor(executor)

    def time(self):
        """Return Trio's idea of the current time.
        """
        if self._task is None:
            raise RuntimeError("This loop is closed.")
        return self._task._runner.clock.current_time()

    # A future doesn't require a trio_asyncio loop
    run_aio_future = staticmethod(run_aio_future)

    # A coroutine (usually) does.
    async def run_aio_coroutine(self, coro):
        """Schedule an asyncio-flavored coroutine for execution on this loop
        by wrapping it in an `asyncio.Task`. Wait for it to complete,
        then return or raise its result.

        Cancelling the current Trio scope will cancel the coroutine,
        which will throw a single `asyncio.CancelledError` into the coroutine
        (just like the usual asyncio behavior). If the coroutine then
        exits with a `~asyncio.CancelledError` exception, the call to
        :meth:`run_aio_coroutine` will raise `trio.Cancelled`.
        But if it exits with `~asyncio.CancelledError` when the current
        Trio scope was *not* cancelled, the `~asyncio.CancelledError` will
        be passed along unchanged.

        This is a Trio-flavored async function.

        """
        self._check_closed()
        t = sniffio.current_async_library_cvar.set("asyncio")
        fut = asyncio.ensure_future(coro, loop=self)
        try:
            return await run_aio_future(fut)
        finally:
            sniffio.current_async_library_cvar.reset(t)

    def trio_as_future(self, proc, *args):
        """Start a new Trio task to run ``await proc(*args)`` asynchronously.
        Return an `asyncio.Future` that will resolve to the value or exception
        produced by that call.

        Errors raised by the Trio call will only be used to resolve
        the returned Future; they won't be propagated in any other
        way. Thus, if you want to notice exceptions, you had better
        not lose track of the returned Future.  The easiest way to do this is
        to immediately await it in an asyncio-flavored function:
        ``await loop.trio_as_future(trio_func, *args)``.

        Note that it's the awaiting of the returned future, not the
        call to :meth:`trio_as_future` itself, that's
        asyncio-flavored. You can call :meth:`trio_as_future` in a
        Trio-flavored function or even a synchronous context, as long
        as you plan to do something with the returned Future other
        than immediately awaiting it.

        Cancelling the future will cancel the Trio task running your
        function, or prevent it from starting if that is still possible.
        If the Trio task exits due to this cancellation, the future
        will resolve to an `asyncio.CancelledError`.

        Arguments:
          proc: a Trio-flavored async function
          args: arguments for *proc*

        Returns:
          an `asyncio.Future` which will resolve to the result of the call to *proc*
        """
        f = asyncio.Future(loop=self)
        self._queue_handle(AsyncHandle(proc, args, self, result_future=f))
        return f

    def run_trio_task(self, proc, *args):
        """Start a new Trio task to run ``await proc(*args)`` asynchronously.
        If it raises an exception, allow the exception to propagate out of
        the trio-asyncio event loop (thus terminating it).

        Arguments:
          proc: a Trio-flavored async function
          args: arguments for *proc*

        Returns:
          an `asyncio.Handle` which can be used to cancel the background task
        """
        return self._queue_handle(AsyncHandle(proc, args, self))

    # Callback handling #

    def _queue_handle(self, handle):
        """Queue a :class:`Handle` or :class:`TimerHandle` to be executed
        by the event loop.

        :param handle: A handle for the code to be executed
        :type handle: :class:`Handle` or :class:`TimerHandle`
        :return: the handle, for convenience.
        """
        raise RuntimeError("override me")

    def _call_soon(self, *arks, **kwargs):
        raise RuntimeError("_call_soon() should not have been called")

    def call_later(self, delay, callback, *args, **context):
        """asyncio's timer-based delay

        Note that the callback is a sync function.

        :param delay: Time to wait, in seconds.
        :param callback: Sync function to call.
        :return: a handle which may be used to cancel the timer.
        """
        self._check_callback(callback, 'call_later')
        assert delay >= 0, delay
        h = asyncio.TimerHandle(delay + self.time(), callback, args, self, **context)
        self._queue_handle(h)
        return h

    def call_at(self, when, callback, *args, **context):
        """asyncio's time-based delay

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_at')
        return self._queue_handle(asyncio.TimerHandle(when, callback, args, self, **context))

    def call_soon(self, callback, *args, **context):
        """asyncio's defer-to-mainloop callback executor.

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_soon')
        return self._queue_handle(asyncio.Handle(callback, args, self, **context))

    def call_soon_threadsafe(self, callback, *args, **context):
        """asyncio's thread-safe defer-to-mainloop

        Note that the callback is a sync function.
        """
        self._check_callback(callback, 'call_soon_threadsafe')
        self._check_closed()
        h = asyncio.Handle(callback, args, self, **context)
        self._token.run_sync_soon(self._q_send.send_nowait, h)

    # drop all timers

    def _cancel_timers(self):
        for tm in self._timers:
            tm.cancel()
        self._timers.clear()

    # supersede some built-ins which should not be used

    def _add_callback(self, handle, _via_token=False):
        raise RuntimeError("_add_callback() should have been superseded")

    def _add_callback_signalsafe(self, handle):  # pragma: no cover
        raise RuntimeError("_add_callback_signalsafe() should have been superseded")

    def _handle_signal(self, signum):
        raise RuntimeError("_handle_signal() should have been superseded")

    def _timer_handle_cancelled(self, handle):
        pass

    # Subprocess handling #

    if not _mswindows:

        async def _make_subprocess_transport(
                self, protocol, args, shell, stdin, stdout, stderr, bufsize, extra=None, **kwargs
        ):
            """Make a subprocess transport. Asyncio context."""

            waiter = self.create_future()
            transp = asyncio.unix_events._UnixSubprocessTransport(
                self,
                protocol,
                args,
                shell,
                stdin,
                stdout,
                stderr,
                bufsize,
                waiter=waiter,
                extra=extra,
                **kwargs
            )

            async def child_wait(transp):
                returncode = await wait_for_child(transp.get_pid())
                transp._process_exited(returncode)

            self.run_trio_task(child_wait, transp)
            try:
                await waiter
            except BaseException as exc:
                # Workaround CPython bug #23353: using yield/yield-from in an
                # except block of a generator doesn't clear properly
                # sys.exc_info()
                err = exc
            else:
                err = None

            if err is not None:
                transp.close()
                await transp._wait()
                raise err

            return transp

    # Thread handling #

    def run_in_executor(self, executor, func, *args):
        """
        Delegate running a synchronous function to a separate thread.

        Limitation:
        The executor must be None, or a (subclass of) ``TrioExecutor``.

        Returns an asyncio.Future.
        """
        self._check_callback(func, 'run_in_executor')
        self._check_closed()
        if executor is None:  # pragma: no branch
            executor = self._default_executor
        assert isinstance(executor, TrioExecutor)
        return self.trio_as_future(executor.submit, func, *args)

    async def synchronize(self):
        """Suspend execution until all callbacks previously scheduled using
        ``call_soon()`` have been processed.

        This is a Trio-flavored async function.

        From asyncio, call ``await trio_as_aio(loop.synchronize)()``
        instead of ``await asyncio.sleep(0)`` if you need to process all
        queued callbacks.

        """
        w = trio.Event()
        self._queue_handle(asyncio.Handle(w.set, (), self))
        await w.wait()

    # Signal handling #

    def _handle_sig(self, sig, _):
        """Helper to safely enqueue a signal handler."""
        h = self._signal_handlers[sig]
        self._token.run_sync_soon(self._q_send.send_nowait, h)

    def add_signal_handler(self, sig, callback, *args):
        """asyncio's method to add a signal handler.
        """
        self._check_closed()
        self._check_signal(sig)
        if sig == signal.SIGKILL:
            raise RuntimeError("SIGKILL cannot be caught")
        h = asyncio.Handle(callback, args, self)
        assert sig not in self._signal_handlers, \
            "Signal %d is already being caught" % (sig,)
        self._orig_signals[sig] = signal.signal(sig, self._handle_sig)
        self._signal_handlers[sig] = h

    def remove_signal_handler(self, sig):
        """asyncio's method to remove a signal handler.
        """
        # self._check_signal(sig)
        try:
            h = self._signal_handlers.pop(sig)
        except KeyError:
            return False
        h.cancel()
        signal.signal(sig, self._orig_signals[sig])
        del self._orig_signals[sig]
        return True

    # File descriptor callbacks #

    # reading from a file descriptor

    def add_reader(self, fd, callback, *args):
        """asyncio's method to call a function when a file descriptor is
        ready for reading.

        This creates a new Trio task. You may want to use "await
        :obj:`trio.lowlevel.wait_readable` (fd)" instead, or

        :param fd: Either an integer (Unix file descriptor) or an object
                   with a ``fileno`` method providing one.
        :return: A handle. To remove the listener, either call
                 ``handle.cancel()`` or :meth:`.remove_reader` (fd).
        """
        self._ensure_fd_no_transport(fd)
        return self._add_reader(fd, callback, *args)

    def _add_reader(self, fd, callback, *args):
        self._check_closed()
        handle = ScopedHandle(callback, args, self)
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

    async def _reader_loop(self, fd, handle):
        with handle._scope:
            try:
                while True:
                    await _wait_readable(fd)
                    if handle._cancelled:
                        break
                    handle._run()
                    await self.synchronize()
            except Exception as exc:
                handle._raise(exc)

    # writing to a file descriptor

    def add_writer(self, fd, callback, *args):
        """asyncio's method to call a function when a file descriptor is
        ready for writing.

        This creates a new Trio task. You may want to use "await
        :obj:`trio.lowlevel.wait_writable` (fd) instead, or

        :param fd: Either an integer (Unix file descriptor) or an object
                   with a ``fileno`` method providing one.
        :return: A handle. To remove the listener, either call
                 ``handle.cancel()`` or :meth:`remove_writer` (fd).
        """
        self._ensure_fd_no_transport(fd)
        return self._add_writer(fd, callback, *args)

    # remove_writer: unchanged from asyncio

    def _add_writer(self, fd, callback, *args):
        self._check_closed()
        handle = ScopedHandle(callback, args, self)
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

    async def _writer_loop(self, fd, handle):
        with handle._scope:
            try:
                while True:
                    await _wait_writable(fd)
                    if handle._cancelled:
                        break
                    handle._run()
                    await self.synchronize()
            except Exception as exc:
                handle._raise(exc)

    def autoclose(self, fd):
        """
        Mark a file descriptor so that it's auto-closed along with this loop.

        This is a safety measure. You also should use appropriate
        finalizers.

        Calling this method twice on the same file descriptor has no effect.

        :param fd: Either an integer (Unix file descriptor) or an object
                   with a ``fileno`` method providing one.
        """
        if hasattr(fd, 'fileno'):
            fd = fd.fileno()
        self._close_files.add(fd)

    def no_autoclose(self, fd):
        """
        Un-mark a file descriptor so that it's no longer auto-closed
        along with this loop.

        Call this method either before closing the file descriptor, or when
        passing it to code out of this loop's scope.

        :param fd: Either an integer (Unix file descriptor) or an object
                   with a ``fileno()`` method providing one.
        :raises KeyError: if the descriptor is not marked to be auto-closed.
        """
        if hasattr(fd, 'fileno'):
            fd = fd.fileno()
        self._close_files.remove(fd)

    # drop all file descriptors, optionally close them

    def _cancel_fds(self):
        """Clean up all of thsi loop's open read or write requests"""
        for fd, key in list(self._selector.get_map().items()):
            for flag in (0, 1):
                if key.events & (1 << flag):
                    handle = key.data[flag]
                    assert handle is not None
                    if not handle._cancelled:  # pragma: no branch
                        if handle._scope is not None:
                            handle._scope.cancel()
            if fd in self._close_files:
                os.close(fd)

    # The actual Trio-based main loop #

    async def _main_loop_init(self, nursery):
        """Set up the loop's internals"""
        if self._nursery is not None or not self._stopped.is_set():
            raise RuntimeError("You can't enter a loop twice")
        self._nursery = nursery
        self._task = trio.lowlevel.current_task()
        self._token = trio.lowlevel.current_trio_token()

    async def _main_loop(self, task_status=trio.TASK_STATUS_IGNORED):
        """Run the loop by processing its event queue.

        This is the core of trio-asyncio's replacement
        of the asyncio main loop.

        Do not call this method directly.
        """

        self._stopped = trio.Event()
        task_status.started()
        sniffio.current_async_library_cvar.set("asyncio")

        try:
            # The shield here ensures that if the context surrounding
            # the loop is cancelled, we keep processing callbacks
            # until we reach the callback inserted by stop().
            # That's important to maintain the asyncio invariant
            # that everything you schedule before stop() will run
            # before the loop stops. In order to be safe against
            # deadlocks, it's important that the surrounding
            # context ensure that stop() gets called upon a
            # cancellation. (open_loop() does this indirectly
            # by calling _main_loop_exit().)
            with trio.CancelScope(shield=True):
                while not self._stopped.is_set():
                    await self._main_loop_one()
        except StopAsyncIteration:
            # raised by .stop_me() to interrupt the loop
            pass
        finally:
            # Signal that the loop is no longer running
            self._stopped.set()

    async def _main_loop_one(self, no_wait=False):
        obj = None
        if self._timers:
            timeout = self._timers[0]._when - self.time()
            if timeout <= 0:
                # If the timer ran out, process the object now.
                obj = heapq.heappop(self._timers)
        else:
            timeout = math.inf

        if obj is None:
            if no_wait:
                obj = self._q_recv.receive_nowait()
            else:
                with trio.move_on_after(timeout):
                    obj = await self._q_recv.receive()
                if obj is None:
                    # Timeout reached. Presumably now a timer is ready,
                    # so restart from the beginning.
                    return

            if isinstance(obj, asyncio.TimerHandle):
                # A TimerHandle is added to the list of timers.
                heapq.heappush(self._timers, obj)
                return

        # assert isinstance(obj, asyncio.Handle) # speed-up
        # Hopefully one of ours
        # but it might be a standard asyncio handle

        if obj._cancelled:
            # simply skip cancelled handlers
            return

        # Don't go through the expensive nursery dance
        # if this is a sync function.
        if isinstance(obj, AsyncHandle):
            if hasattr(obj, '_context'):
                obj._context.run(self._nursery.start_soon, obj._run, name=obj._callback)
            else:
                self._nursery.start_soon(obj._run, name=obj._callback)
            await obj._started.wait()
        else:
            if hasattr(obj, '_context'):
                obj._context.run(obj._callback, *obj._args)
            else:
                obj._callback(*obj._args)

    async def _main_loop_exit(self):
        """Finalize the loop. It may not be re-entered."""
        if self._closed:
            return

        with trio.CancelScope(shield=True):
            # wait_stopped() will return once _main_loop() exits.
            # stop() inserts a callback that will cause such, and
            # _main_loop() doesn't block except to wait for new
            # callbacks to be added, so this should be deadlock-proof.
            self.stop()
            await self.wait_stopped()

            # Drain all remaining callbacks, even those after an initial
            # call to stop(). This avoids deadlocks in some cases if
            # work is submitted to the loop after the shutdown process
            # starts. TODO: figure out precisely what this helps with,
            # maybe find a better way. test_wrong_context_manager_order
            # deadlocks if we remove it for now.
            while True:
                try:
                    await self._main_loop_one(no_wait=True)
                except trio.WouldBlock:
                    break
                except StopAsyncIteration:
                    pass

        # Kill off unprocessed work
        self._cancel_fds()
        self._cancel_timers()

        # clean core fields
        self._nursery = None
        self._task = None

    def is_running(self):
        if self._stopped is None:
            return False
        return not self._stopped.is_set()

    def run_forever(self):
        """asyncio's method to run the loop until it is stopped.
        """
        raise RuntimeError("This is not a sync loop")

    def run_until_complete(self, coro_or_future):
        """asyncio's method to run the loop until the coroutine returns /
        the future completes.
        """
        raise RuntimeError("This is not a sync loop")

    async def wait_stopped(self):
        """Wait until the event loop has stopped.

        This is a Trio-flavored async function. You should call it from
        somewhere outside the ``async with open_loop()`` block to avoid
        a deadlock (the event loop can't stop until all Trio tasks started
        within its scope have exited).
        """
        await self._stopped.wait()

    def stop(self):
        """Halt the main loop.

        Note that only sync loops may be restarted.
        """
        raise RuntimeError("override me")

    def close(self):
        if self._closed:
            return
        self._close()
        super().close()

    def _close(self):
        """Hook for actually closing down the concrete loop."""
        pass

    def __aenter__(self):
        raise RuntimeError("You need to use 'async with open_loop()'.")

    def __aexit__(self, *tb):
        raise RuntimeError("You need to use 'async with open_loop()'.")

    def __enter__(self):
        raise RuntimeError("You need to use a sync loop, or 'async with open_loop()'.")

    def __exit__(self, *tb):
        raise RuntimeError("You need to use a sync loop, or 'async with open_loop()'.")
