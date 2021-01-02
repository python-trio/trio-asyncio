# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import types

import asyncio
import trio_asyncio
from contextvars import ContextVar

from ._util import run_aio_generator, run_aio_future, run_trio_generator
from ._loop import current_loop

from functools import partial


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
        """Support for commonly used (but not recommended) "await aio_as_trio(proc(*args))"
        """
        f = self.proc
        if not hasattr(f, "__await__"):
            f = _call_defer(f, *self.args)
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
    """Return a Trio-flavored wrapper for an asyncio-flavored awaitable,
    async function, async context manager, or async iterator.

    Alias: ``asyncio_as_trio()``

    This is the primary interface for calling asyncio code from Trio code.
    You can also use it as a decorator on an asyncio-flavored async function;
    the decorated function will be callable from Trio-flavored code without
    additional boilerplate.

    Note that while adapting coroutines, i.e.::

        await aio_as_trio(proc(*args))

    is supported (because asyncio uses them a lot) they're not a good
    idea because setting up the coroutine won't run within an asyncio
    context. If possible, use::

        await aio_as_trio(proc)(*args)

    instead.
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
    """Return an asyncio-flavored wrapper for a Trio-flavored async
    function, async context manager, or async iterator.

    Alias: ``trio_as_asyncio()``

    This is the primary interface for calling Trio code from asyncio code.
    You can also use it as a decorator on a Trio-flavored async function;
    the decorated function will be callable from asyncio-flavored code without
    additional boilerplate.

    Note that adapting coroutines, i.e.::

        await trio_as_aio(proc(*args))

    is not supported, because Trio does not expose the existence of coroutine
    objects in its API. Instead, use::

        await trio_as_aio(proc)(*args)

    Or if you already have ``proc(*args)`` as a single object ``coro`` for
    some reason::

        await trio_as_aio(lambda: coro)()

    .. warning:: Be careful when using this to wrap an async context manager.
       There is currently no mechanism for running the entry and exit in
       the same Trio task, so if the async context manager wraps a nursery,
       havoc is likely to result. That is, instead of::

           async def some_aio_func():
               async with trio_asyncio.trio_as_aio(trio.open_nursery()) as nursery:
                   # code that uses nursery -- this will blow up

       do something like::

           async def some_aio_func():
               @trio_asyncio.aio_as_trio
               async def aio_body(nursery):
                   # code that uses nursery -- this will work

               @trio_asyncio.trio_as_aio
               async def trio_body():
                   async with trio.open_nursery() as nursery:
                       await aio_body(nursery)

               await trio_body()

    """
    return Trio_Asyncio_Wrapper(proc, loop=loop)


trio_as_asyncio = trio_as_aio

_shim_running = ContextVar("shim_running", default=False)


@types.coroutine
def _allow_asyncio(fn, *args):
    shim = _shim_running
    shim.set(True)

    coro = fn(*args)
    # start the coroutine
    if isinstance(coro, asyncio.Future):
        return (yield from trio_asyncio.run_aio_future(coro))

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
    """Execute ``await fn(*args)`` in a context that allows ``fn`` to call
    both Trio-flavored and asyncio-flavored functions without marking
    which ones are which.

    This is a Trio-flavored async function. There is no asyncio-flavored
    equivalent.

    This wrapper allows you to indiscrimnately mix :mod:`trio` and
    :mod:`asyncio` functions, generators, or iterators::

        import trio
        import asyncio
        import trio_asyncio

        async def hello(loop):
            await asyncio.sleep(1)
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
    """
    shim = _shim_running
    if shim.get():  # nested call: skip
        return await fn(*args)
    token = shim.set(True)
    try:
        return await _allow_asyncio(fn, *args)
    finally:
        shim.reset(token)
