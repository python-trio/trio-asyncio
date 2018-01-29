# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import trio
import asyncio

import logging
logger = logging.getLogger(__name__)

from .util import run_future
from .handles import *
from .async import *

__all__ = ['open_loop', 'run_trio','run_future','run_coroutine','run_asyncio']



class _TrioPolicy(asyncio.events.BaseDefaultEventLoopPolicy):
    _loop_factory = TrioEventLoop

    def __init__(self):
        super().__init__()
        self._trio_local = trio.TaskLocal(_loop=None, _task=False)

    def new_event_loop(self):
        try:
            task = trio.hazmat.current_task()
        except RuntimeError:
            from .sync import SyncTrioEventLoop
            return SyncTrioEventLoop()
        else:
            raise RuntimeError("You're within a Trio environment.\n"
                "Use 'async with open_loop()' instead.")

    def get_event_loop(self):
        """Get the current event loop.

        Note that this will auto-generate an event loop if none exists, for
        compatibility with asyncio.

        To get a Trio-compatible asyncio loop, use
        ``async with trio_asyncio.open_loop() as loop:``.

        To test whether an event loop is running, check the loop policy's
        ``.current_event_loop`` property.
        """
        try:
            task = trio.hazmat.current_task()
        except RuntimeError: # no Trio task is active
            # this creates a new loop in the main task
            return super().get_event_loop()
        else:
            return self._trio_local._loop

    @property
    def current_event_loop(self):
        """The currently-running event loop, if one exists."""
        try:
            return self._trio_local._loop
        except RuntimeError:
            # in the main thread this would create a new loop
            #return super().get_event_loop()
            return self._local._loop

    def set_event_loop(self, loop):
        """Set the current event loop."""
        try:
            task = trio.hazmat.current_task()
        except RuntimeError:
            return super().set_event_loop(loop)

        # This test will not trigger if you create a new asyncio event loop
        # in a sub-task, which is exactly what we intend to be possible
        if self._trio_local._loop is not None and loop is not None and \
            self._trio_local._task == task:
            raise RuntimeError('You cannot replace an event loop.')
        self._trio_local._loop = loop
        self._trio_local._task = task

class TrioPolicy(_TrioPolicy, asyncio.DefaultEventLoopPolicy):
    pass

async def run_asyncio(proc, *args):
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return await loop.run_asyncio(proc, *args)

async def run_coroutine(fut, scope=None):
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return await loop.run_coroutine(fut, scope=scope)

def run_trio(proc, *args):
    """Call an asynchronous Trio function from asyncio.

    Returns a Future with the result / exception.

    Cancelling the future will cancel the Trio task running your
    function, or prevent it from starting if that is still possible.

    You need to handle errors yourself.
    """
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    return loop.run_trio(proc, *args)

def run_trio_task(proc, *args):
    """Call an asynchronous Trio function from asyncio.

    This method starts the task in the background and returns immediately.
    It does not return a value.

    An uncaught error will propagate to, and terminate, the trio-asyncio loop.
    """
    loop = asyncio.get_event_loop()
    if not isinstance(loop, TrioEventLoop):
        raise RuntimeError("Need to run in a trio_asyncio.open_loop() context")
    loop.run_trio_task(proc, *args)

asyncio.set_event_loop_policy(TrioPolicy())

