import trio
import asyncio
import greenlet
import outcome
import threading
from contextlib import contextmanager

from .base import BaseTrioEventLoop
from .handles import Handle


def _is_main_thread_and_main_greenlet():
    import signal
    import greenlet

    try:
        signal.signal(signal.SIGINT, signal.getsignal(signal.SIGINT))
    except ValueError:
        return False
    else:
        return greenlet.getcurrent().parent is None

trio._util.is_main_thread.__code__ = _is_main_thread_and_main_greenlet.__code__


__all__ = ['SyncTrioEventLoop']


class SyncTrioEventLoop(BaseTrioEventLoop):
    """
    This is the "compatibility mode" implementation of the Trio/asyncio
    event loop. It allows the event loop to be started and stopped multiple
    times, as many older asyncio tests require, by suspending a call to
    :func:`trio.run` using the :mod:`greenlet` library.

    For best results, you should use the asynchronous
    :class:`trio_asyncio.TrioEventLoop` – if possible.
    """

    _control_greenlet = None
    _loop_greenlet = None
    _loop_trio_globals = (None, None)
    _stop_pending = False

    def __init__(self):
        super().__init__()
        self._ensure_loop_ready()
    
    def _queue_handle(self, handle):
        self._check_closed()
        self._q_send.send_nowait(handle)
        return handle

    def _run_loop(self):
        from .loop import current_loop

        async def async_switch(send):
            receive = None

            def switch_outside_context(_):
                nonlocal receive
                receive = outcome.capture(self._control_greenlet.switch, send)
                return trio.hazmat.Abort.SUCCEEDED

            with trio.CancelScope() as scope:
                scope.cancel()
                await trio.hazmat.wait_task_rescheduled(switch_outside_context)

            return receive.unwrap()

        async def trio_main():
            async with trio.open_nursery() as nursery:
                old_loop = current_loop.set(self)
                try:
                    await self._main_loop_init(nursery)
                    while await async_switch("next"):
                        await self._main_loop()
                finally:
                    try:
                        with trio.CancelScope(shield=True):
                            await self._main_loop_exit()
                    finally:
                        nursery.cancel_scope.cancel()
                        current_loop.reset(old_loop)

        try:
            trio.run(trio_main)
            return "done"
        finally:
            self._control_greenlet = None
            self._loop_greenlet = None

    def _ensure_loop_ready(self):
        if self._loop_greenlet is None:
            self._control_greenlet = greenlet.getcurrent()
            self._loop_greenlet = greenlet.greenlet(self._run_loop)
            with self._using_loop_trio_globals():
                response = self._loop_greenlet.switch()
            assert response == "next"
        elif self._control_greenlet is not greenlet.getcurrent():
            raise RuntimeError(
                "The same sync loop can't be controlled from multiple greenlets. "
                "Either you're trying to call run_forever() or run_until_complete() "
                "while another loop is running, or you're combining trio-asyncio with "
                "some other use of greenlets. Neither is supported."
            )

    def run_forever(self):
        self._ensure_loop_ready()
        with self._using_loop_trio_globals():
            response = self._loop_greenlet.switch(True)
        assert response == "next"

    def run_until_complete(self, coro_or_future):
        self._ensure_loop_ready()
        future = asyncio.ensure_future(coro_or_future, loop=self)
        result = None

        def is_done(_):
            nonlocal result

            result = outcome.capture(future.result)
            self.stop()

        future.add_done_callback(is_done)
        with self._using_loop_trio_globals():
            response = self._loop_greenlet.switch(True)
        assert response == "next"

        if result is None:
            raise RuntimeError("Event loop stopped before Future completed.")
        return result.unwrap()

    def stop(self):
        if greenlet.getcurrent() is not self._loop_greenlet:
            raise RuntimeError("Can only stop a sync loop from inside the loop")

        def stop_me():
            self._stop_pending = False
            raise StopAsyncIteration

        if not self._stopped.is_set() and not self._stop_pending:
            self._stop_pending = True
            self._queue_handle(Handle(stop_me, (), self, context=None, is_sync=True))

    def _close(self):
        self._ensure_loop_ready()
        with self._using_loop_trio_globals():
            response = self._loop_greenlet.switch(False)
        assert response == "done"

    def _add_writer(self, fd, callback, *args):
        with self._using_loop_trio_globals():
            super()._add_writer(fd, callback, *args)

    def _add_reader(self, fd, callback, *args):
        with self._using_loop_trio_globals():
            super()._add_reader(fd, callback, *args)

    def _get_trio_globals(self):
        context = trio._core._run.GLOBAL_RUN_CONTEXT
        return (getattr(context, "runner", None), getattr(context, "task", None))

    def _set_trio_globals(self, values):
        runner, task = values
        context = trio._core._run.GLOBAL_RUN_CONTEXT
        if runner is not None:
            context.runner = runner
        elif hasattr(context, "runner"):
            del context.runner
        if task is not None:
            context.task = task
        elif hasattr(context, "task"):
            del context.task

    @contextmanager
    def _using_loop_trio_globals(self):
        saved_globals = self._get_trio_globals()
        self._set_trio_globals(self._loop_trio_globals)
        try:
            yield
        finally:
            self._loop_trio_globals = self._get_trio_globals()
            self._set_trio_globals(saved_globals)
