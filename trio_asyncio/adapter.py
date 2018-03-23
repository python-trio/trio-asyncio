# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import trio_asyncio

# import logging
# logger = logging.getLogger(__name__)

from functools import wraps, partial

__all__ = ['trio2aio', 'aio2trio']


def trio2aio(proc):
    """Decorate an asyncio function so that it's callable by Trio (only)."""
    @wraps(proc)
    async def call(*args, **kwargs):
        if kwargs:
            proc_ = partial(proc, **kwargs)
        else:
            proc_ = proc
        return await trio_asyncio.run_asyncio(proc_, *args)

    return call


def aio2trio(proc):
    """Decorate a Trio function so that it's callable by asyncio (only)."""
    @wraps(proc)
    async def call(*args, **kwargs):
        if kwargs:
            proc_ = partial(proc, **kwargs)
        else:
            proc_ = proc
        return await trio_asyncio.run_trio(proc_, *args)

    return call


def aio2trio_task(proc):
    @wraps(proc)
    async def call(*args, **kwargs):
        if kwargs:
            proc_ = partial(proc, **kwargs)
        else:
            proc_ = proc
        trio_asyncio.run_trio_task(proc_, *args)

    return call
