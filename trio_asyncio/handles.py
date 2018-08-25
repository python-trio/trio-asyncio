import sys
import trio
import asyncio
import sniffio
try:
    from asyncio.format_helpers import _format_callback, _get_function_source
except ImportError:  # <3.7
    from asyncio.events import _format_callback, _get_function_source

__all__ = ['Handle', 'TimerHandle']


def _format_callback_source(func, args):
    func_repr = _format_callback(func, args, None)
    source = _get_function_source(func)
    if source:  # pragma: no cover
        func_repr += ' at %s:%s' % source
    return func_repr


async def _set_sniff(proc, *args):
    sniffio.current_async_library_cvar.set("trio")
    return await proc(*args)


class _TrioHandle:
    """
    This extends asyncio.Handle by providing:
    * a way to cancel an async callback
    * a way to declare the type of the callback function

    ``is_sync`` may be
    * True: sync function, use _call_sync()
    * False: async function, use _call_async()
    * None: also async, but the callback function accepts
      the handle as its sole argument

    The caller is responsible for checking whether the handle
    has been cancelled before invoking ``call_[a]sync()``.
    """

    def _init(self, is_sync):
        """Secondary init.
        """
        self._is_sync = is_sync
        self._scope = None

    def cancel(self):
        super().cancel()
        if self._scope is not None:
            self._scope.cancel()

    def _cb_future_cancel(self, f):
        """If a Trio task completes an asyncio Future,
        add this callback to the future
        and set ``_scope`` to the Trio cancel scope
        so that the task is terminated when the future gets canceled.

        """
        if f.cancelled():
            self.cancel()

    def _raise(self, exc):
        """This is a copy of the exception handling in asyncio.events.Handle._run()
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

    def _repr_info(self):
        info = [self.__class__.__name__]
        if self._cancelled:
            info.append('cancelled')
        if self._callback is not None:
            info.append(_format_callback_source(self._callback, self._args))
        if self._source_traceback:
            frame = self._source_traceback[-1]
            info.append('created at %s:%s' % (frame[0], frame[1]))
        if self._scope is not None:
            info.append('scope=%s' % repr(self._scope))
        return info

    def _call_sync(self):
        assert self._is_sync
        if self._cancelled:
            return
        self._run()

    if sys.version_info >= (3, 7):

        async def _call_async(self, task_status=trio.TASK_STATUS_IGNORED):
            assert not self._is_sync
            if self._cancelled:
                return
            task_status.started()
            try:
                with trio.open_cancel_scope() as scope:
                    self._scope = scope
                    if self._is_sync is None:
                        await self._context.run(_set_sniff, self._callback, self)
                    else:
                        await self._context.run(_set_sniff, self._callback, *self._args)
            except Exception as exc:
                self._raise(exc)
            finally:
                self._scope = None

    else:  # no contextvars

        async def _call_async(self, task_status=trio.TASK_STATUS_IGNORED):
            assert not self._is_sync
            if self._cancelled:
                return
            task_status.started()
            try:
                with trio.open_cancel_scope() as scope:
                    self._scope = scope
                    if self._is_sync is None:
                        await self._callback(self)
                    else:
                        await self._callback(*self._args)
            except Exception as exc:
                self._raise(exc)
            finally:
                self._scope = None


if sys.version_info >= (3, 7):

    class Handle(_TrioHandle, asyncio.Handle):
        def __init__(self, callback, args, loop, context=None, is_sync=True):
            assert not isinstance(context, bool)
            super().__init__(callback, args, loop, context=context)
            self._init(is_sync)

    class TimerHandle(_TrioHandle, asyncio.TimerHandle):
        def __init__(self, when, callback, args, loop, context=None, is_sync=True):
            assert not isinstance(context, bool)
            super().__init__(when, callback, args, loop, context=context)
            self._init(is_sync)

else:

    class Handle(_TrioHandle, asyncio.Handle):
        def __init__(self, callback, args, loop, context=None, is_sync=True):
            super().__init__(callback, args, loop)
            self._init(is_sync)

    class TimerHandle(_TrioHandle, asyncio.TimerHandle):
        def __init__(self, when, callback, args, loop, context=None, is_sync=True):
            super().__init__(when, callback, args, loop)
            self._init(is_sync)
