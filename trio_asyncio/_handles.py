import sys
import trio
import types
import asyncio
from asyncio.format_helpers import _format_callback, _get_function_source

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


def _format_callback_source(func, args):
    func_repr = _format_callback(func, args, None)
    source = _get_function_source(func)
    if source:  # pragma: no cover
        func_repr += " at %s:%s" % source
    return func_repr


class ScopedHandle(asyncio.Handle):
    """An asyncio.Handle that cancels a trio.CancelScope when the Handle is cancelled.

    This is used to manage installed readers and writers, so that the Trio call to
    wait_readable() or wait_writable() can be cancelled when the handle is.
    """

    __slots__ = ("_scope",)

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._scope = trio.CancelScope()

    def cancel(self):
        super().cancel()
        self._scope.cancel()

    def _repr_info(self):
        return super()._repr_info() + ["scope={!r}".format(self._scope)]

    def _raise(self, exc):
        """This is a copy of the exception handling in asyncio.events.Handle._run().
        It's used to report exceptions that arise when waiting for readability
        or writability, and exceptions in async tasks managed by our subclass
        AsyncHandle.
        """
        cb = _format_callback_source(self._callback, self._args)
        msg = "Exception in callback {}".format(cb)
        context = {
            "message": msg,
            "exception": exc,
            "handle": self,
        }
        if self._source_traceback:
            context["source_traceback"] = self._source_traceback
        self._loop.call_exception_handler(context)


# copied from trio._core._multierror, but relying on traceback constructability
# from Python (as introduced in 3.7) instead of ctypes hackery
def concat_tb(head, tail):
    # We have to use an iterative algorithm here, because in the worst case
    # this might be a RecursionError stack that is by definition too deep to
    # process by recursion!
    head_tbs = []
    pointer = head
    while pointer is not None:
        head_tbs.append(pointer)
        pointer = pointer.tb_next
    current_head = tail
    for head_tb in reversed(head_tbs):
        current_head = types.TracebackType(
            current_head, head_tb.tb_frame, head_tb.tb_lasti, head_tb.tb_lineno
        )
    return current_head


# copied from trio._core._run with minor modifications:
def collapse_exception_group(excgroup):
    """Recursively collapse any single-exception groups into that single contained
    exception.
    """
    exceptions = list(excgroup.exceptions)
    modified = False
    for i, exc in enumerate(exceptions):
        if isinstance(exc, BaseExceptionGroup):
            new_exc = collapse_exception_group(exc)
            if new_exc is not exc:
                modified = True
                exceptions[i] = new_exc

    collapse = getattr(excgroup, "collapse", False) or (  # Trio 0.23.0  # Trio 0.24.0
        getattr(trio._core._run, "NONSTRICT_EXCEPTIONGROUP_NOTE", object())
        in getattr(excgroup, "__notes__", ())
    )
    if len(exceptions) == 1 and collapse:
        exceptions[0].__traceback__ = concat_tb(
            excgroup.__traceback__, exceptions[0].__traceback__
        )
        return exceptions[0]
    elif modified:
        return excgroup.derive(exceptions)
    else:
        return excgroup


def collapse_aware_exception_split(exc, etype):
    if not isinstance(exc, BaseExceptionGroup):
        if isinstance(exc, etype):
            return exc, None
        else:
            return None, exc

    match, rest = exc.split(etype)
    if isinstance(match, BaseExceptionGroup):
        match = collapse_exception_group(match)
    if isinstance(rest, BaseExceptionGroup):
        rest = collapse_exception_group(rest)
    return match, rest


class AsyncHandle(ScopedHandle):
    """A ScopedHandle associated with the execution of a Trio-flavored
    async function.

    If the handle is cancelled, the cancel scope surrounding the async function
    will be cancelled too. It is also possible to link a future to the result
    of the async function. If you do that, the future will evaluate to the
    result of the function, and cancelling the future will cancel the handle too.

    """

    __slots__ = ("_fut", "_started")

    def __init__(self, *args, result_future=None, **kw):
        super().__init__(*args, **kw)
        self._fut = result_future
        self._started = trio.Event()
        if self._fut is not None:

            @self._fut.add_done_callback
            def propagate_cancel(f):
                if f.cancelled():
                    self.cancel()

    async def _run(self):
        self._started.set()
        if self._cancelled:
            return

        try:
            # Run the callback
            with self._scope:
                res = await self._callback(*self._args)

            if self._fut:
                # Propagate result or just-this-handle cancellation to the Future
                if self._scope.cancelled_caught:
                    self._fut.cancel()
                elif not self._fut.cancelled():
                    self._fut.set_result(res)

        except BaseException as exc:
            if not self._fut:
                # Pass Exceptions through the fallback exception
                # handler since they have nowhere better to go. (In an
                # async loop this will still raise the exception out
                # of the loop, terminating it.) Let BaseExceptions
                # escape so that Cancelled and SystemExit work
                # reasonably.
                rest, base = collapse_aware_exception_split(exc, Exception)
                if rest:
                    self._raise(rest)
                if base:
                    raise base
            else:
                # The result future gets all the non-Cancelled
                # exceptions.  Any Cancelled need to keep propagating
                # out of this stack frame in order to reach the cancel
                # scope for which they're intended.  Any non-Cancelled
                # BaseExceptions keep propagating.
                cancelled, rest = collapse_aware_exception_split(exc, trio.Cancelled)
                if not self._fut.cancelled():
                    if rest:
                        self._fut.set_exception(rest)
                    else:
                        self._fut.cancel()
                if cancelled:
                    raise cancelled

        finally:
            # asyncio says this is needed to break cycles when an exception occurs.
            # I'm not so sure, but it doesn't seem to do any harm.
            self = None
