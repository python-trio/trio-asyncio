# coding: utf-8

import trio
import queue
import signal
import asyncio
import outcome
import greenlet
import contextlib

from ._base import BaseTrioEventLoop, TrioAsyncioExit
from ._loop import current_loop


async def _sync(proc, *args):
    return proc(*args)


# Context manager to ensure all between-greenlet switches occur with
# an empty trio run context and unset signal wakeup fd. That way, each
# greenlet can have its own private Trio run.
@contextlib.contextmanager
def clean_trio_state():
    trio_globals = trio._core._run.GLOBAL_RUN_CONTEXT.__dict__
    old_state = trio_globals.copy()
    old_wakeup_fd = None
    try:
        old_wakeup_fd = signal.set_wakeup_fd(-1)
    except ValueError:
        pass  # probably we're on the non-main thread
    trio_globals.clear()
    try:
        yield
    finally:
        if old_wakeup_fd is not None:
            signal.set_wakeup_fd(old_wakeup_fd, warn_on_full_buffer=(not old_state))
        trio_globals.clear()
        trio_globals.update(old_state)


class SyncTrioEventLoop(BaseTrioEventLoop):
    """
    This is the "compatibility mode" implementation of the Trio/asyncio
    event loop. It runs synchronously, by delegating the Trio event loop to
    a separate thread.

    For best results, you should use the asynchronous
    :class:`trio_asyncio.TrioEventLoop` – if possible.
    """

    _loop_running = False
    _stop_pending = False
    _glet = None

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)

        # We must start the Trio loop immediately so that self.time() works
        self._glet = greenlet.greenlet(trio.run)
        with clean_trio_state():
            if not self._glet.switch(self.__trio_main):
                raise RuntimeError("Loop could not be started")

    def stop(self):
        """Halt the main loop.

        Any callbacks queued before this point are processed before
        stopping.

        """

        def do_stop():
            self._stop_pending = False
            raise TrioAsyncioExit("stopping trio-asyncio loop")

        if self._loop_running and not self._stop_pending:
            self._stop_pending = True
            self._queue_handle(asyncio.Handle(do_stop, (), self))

    def _queue_handle(self, handle):
        self._check_closed()
        if self._glet is not greenlet.getcurrent() and self._token is not None:
            self.__run_in_greenlet(_sync, self._q_send.send_nowait, handle)
        else:
            self._q_send.send_nowait(handle)
        return handle

    def run_forever(self):
        self.__run_in_greenlet(self._main_loop)

    def is_running(self):
        if self._closed:
            return False
        return self._loop_running

    def _add_reader(self, fd, callback, *args):
        if self._glet is not greenlet.getcurrent() and self._token is not None:
            self.__run_in_greenlet(_sync, super()._add_reader, fd, callback, *args)
        else:
            super()._add_reader(fd, callback, *args)

    def _add_writer(self, fd, callback, *args):
        if self._glet is not greenlet.getcurrent() and self._token is not None:
            self.__run_in_greenlet(_sync, super()._add_writer, fd, callback, *args)
        else:
            super()._add_writer(fd, callback, *args)

    def _trio_io_cancel(self, cancel_scope):
        if self._glet is not greenlet.getcurrent() and self._token is not None:
            self.__run_in_greenlet(_sync, cancel_scope.cancel)
        else:
            cancel_scope.cancel()

    def run_until_complete(self, future):
        """Run until the Future is done.

        If the argument is a coroutine, it is wrapped in a Task.

        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.

        Return the Future's result, or raise its exception.
        """
        return self.__run_in_greenlet(self._run_coroutine, future)

    async def _run_coroutine(self, future):
        """Helper for run_until_complete().

        We need to make sure that a RuntimeError is raised
        if the loop is stopped before the future completes.

        This code runs in the Trio greenlet.
        """
        result = None
        future = asyncio.ensure_future(future, loop=self)

        def is_done(_):
            nonlocal result

            result = outcome.capture(future.result)
            self.stop()

        future.add_done_callback(is_done)
        try:
            await self._main_loop()
            try:
                while result is None:
                    try:
                        await self._main_loop_one(no_wait=True)
                    except TrioAsyncioExit:
                        pass
            except trio.WouldBlock:
                pass
        finally:
            future.remove_done_callback(is_done)

        if result is None:
            raise RuntimeError("Event loop stopped before Future completed.")
        return result.unwrap()

    def __run_in_greenlet(self, async_fn, *args):
        self._check_closed()
        if self._loop_running:
            raise RuntimeError(
                "You can't nest calls to run_until_complete()/run_forever()."
            )
        if asyncio._get_running_loop() is not None:
            raise RuntimeError(
                "Cannot run the event loop while another loop is running"
            )
        if not self._glet:
            if async_fn is _sync:
                # Allow for cleanups during close()
                sync_fn, *args = args
                return sync_fn(*args)
            raise RuntimeError("The Trio greenlet is not running")
        with clean_trio_state():
            res = self._glet.switch((greenlet.getcurrent(), async_fn, args))
        if res is None:
            raise RuntimeError("Loop has died / terminated")
        return res.unwrap()

    async def __trio_main(self):
        from ._loop import _sync_loop_task_name

        trio.lowlevel.current_task().name = _sync_loop_task_name

        # The non-context-manager equivalent of open_loop()
        async with trio.open_nursery() as nursery:
            await self._main_loop_init(nursery)
            with clean_trio_state():
                req = greenlet.getcurrent().parent.switch(True)

            while not self._closed:
                if req is None:
                    break
                caller, async_fn, args = req

                self._loop_running = True
                asyncio._set_running_loop(self)
                current_loop.set(self)
                result = await outcome.acapture(async_fn, *args)
                asyncio._set_running_loop(None)
                current_loop.set(None)
                self._loop_running = False

                if isinstance(result, outcome.Error) and isinstance(
                    result.error, trio.Cancelled
                ):
                    res = RuntimeError("Main loop cancelled")
                    res.__cause__ = result.error.__cause__
                    result = outcome.Error(res)

                with clean_trio_state():
                    req = caller.switch(result)

            with trio.CancelScope(shield=True):
                await self._main_loop_exit()
            nursery.cancel_scope.cancel()

    def __enter__(self):
        return self

    def __exit__(self, *tb):
        self.stop()
        self.close()
        assert self._glet is None

    def _close(self):
        """Hook to terminate the thread"""
        if self._glet is not None:
            if self._glet is greenlet.getcurrent():
                raise RuntimeError("You can't close a sync loop from the inside")
            # The parent will generally already be this greenlet, but might
            # not be in nested-loop cases.
            self._glet.parent = greenlet.getcurrent()
            with clean_trio_state():
                self._glet.switch(None)
            assert self._glet.dead
            self._glet = None
        super()._close()
