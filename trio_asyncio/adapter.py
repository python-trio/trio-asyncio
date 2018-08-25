# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import types
from async_generator import isasyncgenfunction
import asyncio
import trio_asyncio
from contextvars import copy_context

# import logging
# logger = logging.getLogger(__name__)

from functools import wraps, partial

__all__ = ['trio2aio', 'aio2trio', 'allow_asyncio']


def trio2aio(proc):
    if isasyncgenfunction(proc):

        @wraps(proc)
        def call(*args, **kwargs):
            proc_ = proc
            if kwargs:
                proc_ = partial(proc_, **kwargs)
            return trio_asyncio.wrap_generator(proc_, *args)

    else:

        @wraps(proc)
        async def call(*args, **kwargs):
            proc_ = proc
            if kwargs:
                proc_ = partial(proc_, **kwargs)
            return await trio_asyncio.run_asyncio(proc_, *args)

    return call


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
    :mod:`asyncio` functions, generators, or iterators.

    Unfortunately, this wrapper imposes a slight delay, and there are
    issues with cancellation (specifically, :mod:`asyncio` function will
    see :class:`trio.Cancelled` instead of
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
