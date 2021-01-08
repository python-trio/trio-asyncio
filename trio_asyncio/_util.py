# This code implements helper functions that work without running
# a TrioEventLoop.

import trio
import asyncio
import sys
import outcome
import sniffio


async def run_aio_future(future):
    """Wait for an asyncio-flavored future to become done, then return
    or raise its result.

    Cancelling the current Trio scope will cancel the future.  If this
    results in the future resolving to an `asyncio.CancelledError`
    exception, the call to :func:`run_aio_future` will raise
    `trio.Cancelled`.  But if the future resolves to
    `~asyncio.CancelledError` when the current Trio scope was *not*
    cancelled, the `~asyncio.CancelledError` will be passed along
    unchanged.

    This is a Trio-flavored async function.

    """
    task = trio.lowlevel.current_task()
    raise_cancel = None

    def done_cb(_):
        trio.lowlevel.reschedule(task, outcome.capture(future.result))

    future.add_done_callback(done_cb)

    def abort_cb(raise_cancel_arg):
        # Save the cancel-raising function
        nonlocal raise_cancel
        raise_cancel = raise_cancel_arg
        # Attempt to cancel our future
        future.cancel()
        # Keep waiting
        return trio.lowlevel.Abort.FAILED

    try:
        res = await trio.lowlevel.wait_task_rescheduled(abort_cb)
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


async def run_aio_generator(loop, async_generator):
    """Return a Trio-flavored async iterator which wraps the given
    asyncio-flavored async iterator (usually an async generator, but
    doesn't have to be). The asyncio tasks that perform each iteration
    of *async_generator* will run in *loop*.
    """
    task = trio.lowlevel.current_task()
    raise_cancel = None
    current_read = None

    async def consume_next():
        t = sniffio.current_async_library_cvar.set("asyncio")
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
        finally:
            sniffio.current_async_library_cvar.reset(t)

        trio.lowlevel.reschedule(task, result)

    def abort_cb(raise_cancel_arg):
        # Save the cancel-raising function
        nonlocal raise_cancel
        raise_cancel = raise_cancel_arg

        if not current_read:
            # There is no current read
            return trio.lowlevel.Abort.SUCCEEDED
        else:
            # Attempt to cancel the current iterator read, do not
            # report success until the future was actually cancelled.
            already_cancelled = current_read.cancel()
            if already_cancelled:
                return trio.lowlevel.Abort.SUCCEEDED
            else:
                # Continue dealing with the cancellation once
                # future.cancel() goes to the result of
                # wait_task_rescheduled()
                return trio.lowlevel.Abort.FAILED

    try:
        while True:
            # Schedule in asyncio that we read the next item from the iterator
            current_read = asyncio.ensure_future(consume_next())

            item = await trio.lowlevel.wait_task_rescheduled(abort_cb)

            if item is STOP:
                break
            yield item

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


async def run_trio_generator(loop, async_generator):
    """Run a Trio generator from within asyncio"""
    while True:
        # Schedule in asyncio that we read the next item from the iterator
        try:
            item = await loop.trio_as_future(async_generator.__anext__)
        except StopAsyncIteration:
            break
        else:
            yield item


# Copied from Trio:
def fixup_module_metadata(module_name, namespace):
    seen_ids = set()

    def fix_one(qualname, name, obj):
        # avoid infinite recursion (relevant when using
        # typing.Generic, for example)
        if id(obj) in seen_ids:
            return
        seen_ids.add(id(obj))

        mod = getattr(obj, "__module__", None)
        if mod is not None and mod.startswith("trio_asyncio."):
            obj.__module__ = module_name
            # Modules, unlike everything else in Python, put fully-qualitied
            # names into their __name__ attribute. We check for "." to avoid
            # rewriting these.
            if hasattr(obj, "__name__") and "." not in obj.__name__:
                obj.__name__ = name
                obj.__qualname__ = qualname
            if isinstance(obj, type):
                for attr_name, attr_value in obj.__dict__.items():
                    fix_one(objname + "." + attr_name, attr_name, attr_value)

    for objname, obj in namespace.items():
        if not objname.startswith("_"):  # ignore private attributes
            fix_one(objname, objname, obj)
