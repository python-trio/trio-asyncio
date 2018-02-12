# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import trio_asyncio

# import logging
# logger = logging.getLogger(__name__)

from functools import wraps

__all__ = ['trio2aio', 'aio2trio']


def trio2aio(proc):
    @wraps(proc)
    async def call(*args):
        return await trio_asyncio.run_asyncio(proc, *args)

    return call


def aio2trio(proc):
    @wraps(proc)
    async def call(*args):
        return await trio_asyncio.run_trio(proc, *args)

    return call


def aio2trio_task(proc):
    @wraps(proc)
    async def call(*args):
        trio_asyncio.run_trio_task(proc, *args)

    return call
