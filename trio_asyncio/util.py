# This code implements helper functions that work without running
# a TrioEventLoop.

import trio
import asyncio
import sys
import outcome
from async_generator import async_generator, yield_

__all__ = ['run_future']


async def run_future(future):
    """Wait for an asyncio future/coroutine from Trio code.

    Cancelling the current Trio scope will cancel the future/coroutine.

    Cancelling the future/coroutine will cause an ``asyncio.CancelledError``.
    """
    task = trio.hazmat.current_task()
    raise_cancel = None

    def done_cb(_):
        trio.hazmat.reschedule(task, outcome.capture(future.result))

    future.add_done_callback(done_cb)

    def abort_cb(raise_cancel_arg):
        # Save the cancel-raising function
        nonlocal raise_cancel
        raise_cancel = raise_cancel_arg
        # Attempt to cancel our future
        future.cancel()
        # Keep waiting
        return trio.hazmat.Abort.FAILED

    try:
        res = await trio.hazmat.wait_task_rescheduled(abort_cb)
        return res
    except asyncio.CancelledError as exc:
        if raise_cancel is not None:
            try:
                raise_cancel()
            finally:
                # Try to preserve the exception chain,
                # for more detailed tracebacks
                sys.exc_info()[1].__cause__ = exc
        else:
            raise


STOP = object()


@async_generator
async def run_generator(loop, async_generator):
    task = trio.hazmat.current_task()
    raise_cancel = None
    current_read = None

    async def consume_next():
        try:
            item = await async_generator.__anext__()
            result = outcome.Value(value=item)
        except StopAsyncIteration:
            result = outcome.Value(value=STOP)
        except asyncio.CancelledError:
            # Once we are cancelled, we do not call reschedule() anymore
            return
        except Exception as e:
            result = outcome.Error(error=e)

        trio.hazmat.reschedule(task, result)

    def abort_cb(raise_cancel_arg):
        # Save the cancel-raising function
        nonlocal raise_cancel
        raise_cancel = raise_cancel_arg

        if not current_read:
            # There is no current read
            return trio.hazmat.Abort.SUCCEEDED
        else:
            # Attempt to cancel the current iterator read, do not
            # report success until the future was actually cancelled.
            already_cancelled = current_read.cancel()
            if already_cancelled:
                return trio.hazmat.Abort.SUCCEEDED
            else:
                # Continue dealing with the cancellation once
                # future.cancel() goes to the result of
                # wait_task_rescheduled()
                return trio.hazmat.Abort.FAILED

    try:
        while True:
            # Schedule in asyncio that we read the next item from the iterator
            current_read = asyncio.ensure_future(consume_next(), loop=loop)

            item = await trio.hazmat.wait_task_rescheduled(abort_cb)

            if item is STOP:
                break
            await yield_(item)

    except asyncio.CancelledError as exc:
        if raise_cancel is not None:
            try:
                raise_cancel()
            finally:
                # Try to preserve the exception chain,
                # for more detailed tracebacks
                sys.exc_info()[1].__cause__ = exc
        else:
            raise
