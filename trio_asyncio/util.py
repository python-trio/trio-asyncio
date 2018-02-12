# This code implements helper functions that work without running
# a TrioEventLoop.

import trio
import asyncio
import sys

__all__ = ['run_future']


async def run_future(future):
    """Wait for an asyncio future/coroutine from Trio code.

    Cancelling the current Trio scope will cancel the future/coroutine.

    Cancelling the future/coroutine will cause an ``asyncio.CancelledError``.
    """
    task = trio.hazmat.current_task()
    raise_cancel = None

    print("RUN_F",future)
    def done_cb(_):
        print("RUN_F DONE_CB",_)
        trio.hazmat.reschedule(task, trio.hazmat.Result.capture(future.result))

    future.add_done_callback(done_cb)

    def abort_cb(raise_cancel_arg):
        print("RUN_F ABORT_CB",raise_cancel_arg)
        # Save the cancel-raising function
        nonlocal raise_cancel
        raise_cancel = raise_cancel_arg
        # Attempt to cancel our future
        future.cancel()
        # Keep waiting
        print("RUN_F ABORT_CB FAIL")
        return trio.hazmat.Abort.FAILED

    try:
        print("RUN_F SLEEP")
        try:
            res = await trio.hazmat.wait_task_rescheduled(abort_cb)
        except BaseException as exc:
            print("RUN_F ERR",exc)
            raise
        else:
            print("RUN_F DONE",res)
        return res
    except asyncio.CancelledError as exc:
        if False and raise_cancel is not None:
            try:
                print("RUN_F CANCEL RE")
                raise_cancel()
            finally:
                # Try to preserve the exception chain,
                # for more detailed tracebacks
                sys.exc_info()[1].__cause__ = exc
        else:
            print("RUN_F CANCEL PROP")
            raise
