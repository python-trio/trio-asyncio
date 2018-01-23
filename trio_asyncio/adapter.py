# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import sys
import trio
import asyncio
import math
import heapq
import signal
import threading
import selectors

import logging
logger = logging.getLogger(__name__)

from functools import wraps
from asyncio.events import _format_callback, _get_function_source
from selectors import _BaseSelectorImpl, EVENT_READ, EVENT_WRITE

__all__ = ['trio2aio','aio2trio']


def trio2aio(loop='loop'):
    def adapter(proc):
        @wraps(proc)
        async def call(self, *args):
            loop_ = getattr(self, loop)
            return await loop_.run_asyncio(proc, self, *args)
        return call
    if callable(loop):
        proc,loop = loop,'loop'
        return adapter(proc)
    else:
        return adapter


def aio2trio(loop='loop'):
    def adapter(proc):
        @wraps(proc)
        async def call(self, *args):
            loop_ = getattr(self, loop)
            return await loop_.run_trio(proc, self, *args)
        return call
    if callable(loop):
        proc,loop = loop,'loop'
        return adapter(proc)
    else:
        return adapter

