import trio

from ._base import BaseTrioEventLoop
from ._handles import Handle


class TrioEventLoop(BaseTrioEventLoop):
    """A Trio-compatible asyncio event loop.

    This loop runs in an async Trio context.
    """

    def _queue_handle(self, handle):
        self._check_closed()
        self._q_send.send_nowait(handle)
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
            if self._stop_wait is not None:
                return self._stop_wait
            waiter = self._stop_wait = trio.Event()
        else:
            if waiter.is_set():
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
