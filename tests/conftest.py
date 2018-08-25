# XX this does not belong here -- b/c it's here, these things only apply to
# the tests in trio/_core/tests, not in trio/tests. For now there's some
# copy-paste...
#
# this stuff should become a proper pytest plugin

import pytest
import asyncio
import trio_asyncio
import trio_asyncio.loop as loop_
import inspect
from async_generator import async_generator, yield_

# Hacks for <3.7
if not hasattr(asyncio, 'run'):

    def run(main, *, debug=False):
        loop = asyncio.new_event_loop()
        loop.set_debug(debug)
        return loop.run(main)

    asyncio.run = run

if not hasattr(asyncio, 'current_task'):

    def current_task(loop=None):
        return asyncio.Task.current_task(loop)

    asyncio.current_task = current_task

if not hasattr(asyncio, 'all_tasks'):

    def all_tasks(loop=None):
        return asyncio.Task.all_tasks(loop)

    asyncio.all_tasks = all_tasks

if not hasattr(asyncio, 'create_task'):

    if hasattr(asyncio.events, 'get_running_loop'):

        def create_task(coro):
            loop = asyncio.events.get_running_loop()
            return loop.create_task(coro)
    else:

        def create_task(coro):
            loop = asyncio.events._get_running_loop()
            return loop.create_task(coro)

    asyncio.create_task = create_task


@pytest.fixture
@async_generator
async def loop():
    async with trio_asyncio.open_loop() as loop:
        try:
            await yield_( loop)
        finally:
            await loop.stop().wait()


# auto-trio-ize all async functions
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = pytest.mark.trio(pyfuncitem.obj)
