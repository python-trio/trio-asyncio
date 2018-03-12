import trio
import asyncio

from async_generator import async_generator, yield_, asynccontextmanager

from .base import BaseTrioEventLoop
from .handles import Handle

__all__ = ['TrioEventLoop', 'open_loop']


class TrioEventLoop(BaseTrioEventLoop):
    """A Trio-compatible asyncio event loop.

    This loop runs in an async Trio context. If you really do need a
    stand-alone implementation, use :class:`SyncTrioEventLoop`.
    """

    def _queue_handle(self, handle):
        self._check_closed()
        self._q.put_nowait(handle)
        return handle

    def default_exception_handler(self, context):
        """Default exception handler.

        This default handler simply re-raises an exception if there is one.

        Rationale:

        In traditional asyncio, there frequently is no context which the
        exception is supposed to affect.

        Trio-asyncio, however, collects the loop and all its tasks in a
        nursery. Thus the context which must be aborted, and thus in which
        the error needs to be raised, is known / can easily be controlled
        by the programmer.

        For maximum compatibility, this default handler is only used in
        asynchronous loops.
        """
        # TODO: add context.get('handle') to the exception

        exception = context.get('exception')
        if exception is None:
            message = context.get('message')
            if not message:
                message = 'Unhandled error in event loop'
            raise RuntimeError(message)
        else:
            raise exception

    def stop(self, waiter=None):
        """Halt the main loop.

        (Or rather, tell it to halt itself soon(ish).)

        :param waiter: an Event that is set when the loop is stopped.
        :type waiter: :class:`trio.Event`
        :return: Either the Event instance that was passed in,
                 or a newly-allocated one.

        """
        if waiter is None:
            waiter = trio.Event()
        else:
            waiter.clear()

        def stop_me():
            waiter.set()
            raise StopAsyncIteration

        if self._stopped.is_set():
            waiter.set()
        else:
            self._queue_handle(Handle(stop_me, (), self, context=None, is_sync=True))
        return waiter

    def _close(self):
        """Hook for actually closing down things."""
        if not self._stopped.is_set():
            raise RuntimeError("You need to stop the loop before closing it")
        super()._close()


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
        old_loop = asyncio.get_event_loop()
        loop = TrioEventLoop(queue_len=queue_len)
        try:
            loop._closed = False
            asyncio.set_event_loop(loop)
            await loop._main_loop_init(nursery)
            await nursery.start(loop._main_loop)
            await yield_(loop)
        finally:
            try:
                await loop.stop().wait()
            finally:
                await loop._main_loop_exit()
                loop.close()
                asyncio.set_event_loop(old_loop)
                nursery.cancel_scope.cancel()
