import sys
import trio
import asyncio
import sniffio
try:
    from asyncio.format_helpers import _format_callback, _get_function_source
except ImportError:  # <3.7
    from asyncio.events import _format_callback, _get_function_source


def _format_callback_source(func, args):
    func_repr = _format_callback(func, args, None)
    source = _get_function_source(func)
    if source:  # pragma: no cover
        func_repr += ' at %s:%s' % source
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
        msg = 'Exception in callback {}'.format(cb)
        context = {
            'message': msg,
            'exception': exc,
            'handle': self,
        }
        if self._source_traceback:
            context['source_traceback'] = self._source_traceback
        self._loop.call_exception_handler(context)


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
        sniffio.current_async_library_cvar.set("trio")
        self._started.set()
        if self._cancelled:
            return

        def report_exception(exc):
            if not isinstance(exc, Exception):
                # Let BaseExceptions such as Cancelled escape without being noted.
                return exc
            # Otherwise defer to the asyncio exception handler. (In an async loop
            # this will still raise the exception out of the loop, terminating it.)
            self._raise(exc)
            return None

        def remove_cancelled(exc):
            if isinstance(exc, trio.Cancelled):
                return None
            return exc

        def only_cancelled(exc):
            if isinstance(exc, trio.Cancelled):
                return exc
            return None

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
                # Pass Exceptions through the fallback exception handler since
                # they have nowhere better to go. Let BaseExceptions escape so
                # that Cancelled and SystemExit work reasonably.
                with trio.MultiError.catch(report_exception):
                    raise
            else:
                # The result future gets all the non-Cancelled
                # exceptions.  Any Cancelled need to keep propagating
                # out of this stack frame in order to reach the cancel
                # scope for which they're intended.  This would be a
                # great place for ExceptionGroup.split() if we had it.
                cancelled = trio.MultiError.filter(only_cancelled, exc)
                rest = trio.MultiError.filter(remove_cancelled, exc)
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
