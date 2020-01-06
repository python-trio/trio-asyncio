# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import types
import warnings

import asyncio
import trio_asyncio
from contextvars import ContextVar

from .util import run_aio_generator, run_aio_future, run_trio_generator

current_loop = ContextVar('trio_aio_loop', default=None)

# import logging
# logger = logging.getLogger(__name__)

from functools import wraps, partial

__all__ = [
    'trio2aio', 'aio2trio', 'aio_as_trio', 'trio_as_aio', 'allow_asyncio', 'current_loop',
    'asyncio_as_trio', 'trio_as_asyncio'
]


def trio2aio(proc):
    """Call asyncio code from Trio.

        Deprecated: Use aio_as_trio() instead.

        """
    warnings.warn("Use 'aio_as_trio(proc)' instead'", DeprecationWarning)

    return aio_as_trio(proc)


async def _call_defer(proc, *args, **kwargs):
    return await proc(*args, **kwargs)


class Asyncio_Trio_Wrapper:
    """
    This wrapper object encapsulates an asyncio-style coroutine,
    procedure, generator, or iterator, to be called seamlessly from Trio.
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
        """If this is used to decorate an instance/class method,
        we need to forward the original ``self`` to the wrapped method.
        """
        if obj is None:
            return partial(self.__call__, cls)
        return partial(self.__call__, obj)

    async def __call__(self, *args, **kwargs):
        if self.args:
            raise RuntimeError("Call 'aio_as_trio(proc)(*args)', not 'aio_as_trio(proc, *args)'")

        # We route this through _calL_defer because some wrappers require
        # running in asyncio context
        f = _call_defer(self.proc, *args, **kwargs)
        return await self.loop.run_aio_coroutine(f)

    def __await__(self):
        """Compatibility code for "await loop.run_asyncio(coro)"
        """
        f = self.proc
        if not hasattr(f, "__await__"):
            f = f(*self.args)
        elif self.args:
            raise RuntimeError("You can't supply arguments to a coroutine")
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
        proc_iter = getattr(self.proc, "__aiter__", None)
        if proc_iter is None or self.args:
            raise RuntimeError("Call 'aio_as_trio(gen(*args))', not 'aio_as_trio(gen, *args)'")
        return run_aio_generator(self.loop, proc_iter())


def aio_as_trio(proc, *, loop=None):
    """
    Encapsulate an asyncio-style coroutine, procedure, generator, or
    iterator, to be called seamlessly from Trio.

    Note that while adapting coroutines, i.e.::

        wrap(proc(*args))

    is supported (because asyncio uses them a lot) they're not a good
    idea because setting up the coroutine won't run within an asyncio
    context. If at all possible, use::

        wrap(proc, *args)

    instead, which translates to::

        await aio_as_trio(proc)(*args)
    """
    return Asyncio_Trio_Wrapper(proc, loop=loop)


asyncio_as_trio = aio_as_trio


class Trio_Asyncio_Wrapper:
    """
    This wrapper object encapsulates a Trio-style procedure,
    generator, or iterator, to be called seamlessly from asyncio.
    """

    # This class doesn't wrap coroutines because Trio's call convention
    # is
    #     wrap(proc, *args)
    # and not
    #     wrap(proc(*args))

    def __init__(self, proc, loop=None):
        self.proc = proc
        self._loop = loop

    @property
    def loop(self):
        """The loop argument needs to be lazily evaluated."""
        loop = self._loop
        if loop is None:
            loop = current_loop.get()
        return loop

    def __get__(self, obj, cls):
        """If this is used to decorate an instance/class method,
        we need to forward the original ``self`` to the wrapped method.
        """
        if obj is None:
            return partial(self.__call__, cls)
        return partial(self.__call__, obj)

    def __call__(self, *args, **kwargs):
        proc = self.proc
        if kwargs:
            proc = partial(proc, **kwargs)
        return self.loop.trio_as_future(proc, *args)

    def __aenter__(self):
        proc_enter = getattr(self.proc, "__aenter__", None)
        if proc_enter is None:
            raise RuntimeError(
                "Call 'trio_as_aio(ctxfactory(*args))', not 'trio_as_aio(ctxfactory, *args)'"
            )
        return self.loop.trio_as_future(proc_enter)

    def __aexit__(self, *tb):
        proc_exit = self.proc.__aexit__
        return self.loop.trio_as_future(proc_exit, *tb)

    def __aiter__(self):
        proc_iter = getattr(self.proc, "__aiter__", None)
        if proc_iter is None:
            raise RuntimeError("Call 'trio_as_aio(gen(*args))', not 'trio_as_aio(gen, *args)'")
        return run_trio_generator(self.loop, proc_iter())


def trio_as_aio(proc, *, loop=None):
    """
    Encapsulate a Trio-style procedure, generator, or iterator, to be
    called seamlessly from asyncio.

    Note that adapting coroutines, i.e.::

        wrap(proc(*args))

    is not supported: Trio's calling convention is to always use::

        wrap(proc, *args)

    which translates to::

        await trio_as_aio(proc)(*args)
    """
    return Trio_Asyncio_Wrapper(proc, loop=loop)


trio_as_asyncio = trio_as_aio


def aio2trio(proc):
    """Call asyncio code from Trio.

        Deprecated: Use aio_as_trio() instead.

        """
    warnings.warn("Use 'trio_as_aio(proc)' instead'", DeprecationWarning)

    return trio_as_aio(proc)


def aio2trio_task(proc):
    warnings.warn("Use loop.run_trio_task() instead", DeprecationWarning)

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
                next_send = yield from run_aio_future(yielded)
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
    :exc:`concurrent.futures.CancelledError`). Thus, this mode is not the default.

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
