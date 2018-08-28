# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import types
import warnings

from async_generator import isasyncgenfunction
import asyncio
import trio_asyncio
from contextvars import ContextVar

from .util import run_aio_generator, run_aio_future

current_loop = ContextVar('trio_aio_loop', default=None)
current_policy = ContextVar('trio_aio_policy', default=None)

# import logging
# logger = logging.getLogger(__name__)

from functools import wraps, partial

__all__ = ['trio2aio', 'aio2trio', 'aio_as_trio', 'allow_asyncio',
           'current_loop', 'current_policy']


def trio2aio(proc):
        """Call asyncio code from Trio.

        Deprecated: Use aio_as_trio() instead.

            await loop.run_iterator(iter)

        simply call

            await loop.run_asyncio(iter)
        """
        warnings.warn("Use 'aio_as_trio(proc)' instead'", DeprecationWarning)

        return aio_as_trio(proc)

class Asyncio_Trio_Wrapper:
    """
    This wrapper object encapsulates an asyncio-style coroutine,
    generator, or iterator, to be called seamlessly from Trio.
    """
    def __init__(self, proc, args=[], loop=None):
        self.proc = proc
        self.args = args
        self._loop = loop

    @property
    def loop(self):
        """The loop argument needs to be lazily evaluated."""
        loop = self._loop
        if loop is None:
            loop = current_loop.get()
        return loop

    def __get__(self, obj, cls):
        """If this is used to decorate an instance,
        we need to forward the original ``self`` to the wrapped method.
        """
        if obj is None:
            return self.__call__
        return partial(self.__call__, obj)

    async def __call__(self, *args, **kwargs):
        if self.args:
            "Call 'aio_as_trio(oroc)(*args)', not 'aio_as_trio(proc, *args)'"

        f = self.proc(*args, **kwargs)
        return await self.loop.run_aio_coroutine(f)

    def __await__(self):
        """Compatbility code for loop.run_asyncio"""
        f = self.proc(*self.args)
        return self.loop.run_aio_coroutine(f).__await__()

    def __aenter__(self):
        proc_enter = getattr(self.proc, "__aenter__", None)
        if proc_enter is None or self.args:
            raise RuntimeError(
                "Call 'aio_as_trio(ctxfactory(*args))', not 'aio_as_trio(ctxfactory, *args)'"
            )
        f = proc_enter()
        return self.loop.run_aio_coroutine(f)

    def __aexit__(self, *tb):
        f = self.proc.__aexit__(*tb)
        return self.loop.run_aio_coroutine(f)

    def __aiter__(self):
        proc_iter = getattr(self.proc, "__anext__", None)
        if proc_iter is None or self.args:
            raise RuntimeError(
                "Call 'run_asyncio(gen(*args))', not 'run_asyncio(gen, *args)'"
            )
        return run_aio_generator(self.loop, self.proc)


def aio_as_trio(proc, loop=None):
    return Asyncio_Trio_Wrapper(proc, loop=loop)


def aio2trio(proc):
    """Decorate a Trio function so that it's callable by asyncio (only)."""

    @wraps(proc)
    async def call(*args, **kwargs):
        proc_ = proc
        if kwargs:
            proc_ = partial(proc_, **kwargs)
        return await trio_asyncio.run_trio(proc_, *args)

    return call


def aio2trio_task(proc):
    @wraps(proc)
    async def call(*args, **kwargs):
        proc_ = proc
        if kwargs:
            proc_ = partial(proc_, **kwargs)
        trio_asyncio.run_trio_task(proc_, *args)

    return call


@types.coroutine
def _allow_asyncio(fn, *args):
    shim = trio_asyncio.base._shim_running
    shim.set(True)

    coro = fn(*args)
    # start the coroutine
    if isinstance(coro, asyncio.Future):
        return (yield from trio_asyncio.run_future(coro))

    p, a = coro.send, None
    while True:
        try:
            yielded = p(a)
        except StopIteration as e:
            return e.value
        try:
            if isinstance(yielded, asyncio.Future):
                next_send = yield from trio_asyncio.run_future(yielded)
            else:
                next_send = yield yielded
        except BaseException as exc:
            p, a = coro.throw, exc
        else:
            p, a = coro.send, next_send


async def allow_asyncio(fn, *args):
    """
    This wrapper allows you to indiscrimnately mix :mod:`trio` and
    :mod:`asyncio` functions, generators, or iterators::

        import trio
        import asyncio
        import trio_asyncio

        async def hello(loop):
            await asyncio.sleep(1, loop=loop)
            print("Hello")
            await trio.sleep(1)
            print("World")

        async def main():
            with trio_asyncio.open_loop() as loop:
                await trio_asyncio.allow_asyncio(hello, loop)
        trio.run(main)

    Unfortunately, there are issues with cancellation (specifically,
    :mod:`asyncio` function will see :class:`trio.Cancelled` instead of
    :class:`asyncio.CancelledError`). Thus, this mode is not the default.

    This function must be called from :mod:`trio` context.
    """
    shim = trio_asyncio.base._shim_running
    if shim.get():  # nested call: skip
        return await fn(*args)
    token = shim.set(True)
    try:
        return await _allow_asyncio(fn, *args)
    finally:
        shim.reset(token)
