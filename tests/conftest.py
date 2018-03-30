# XX this does not belong here -- b/c it's here, these things only apply to
# the tests in trio/_core/tests, not in trio/tests. For now there's some
# copy-paste...
#
# this stuff should become a proper pytest plugin

import pytest
import asyncio
import trio_asyncio
import inspect

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
async def loop():
    async with trio_asyncio.open_loop() as loop:
        try:
            yield loop
        finally:
            await loop.stop().wait()


@pytest.fixture
def sync_loop():
    loop = asyncio.new_event_loop()
    with loop:
        yield loop


# auto-trio-ize all async functions
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = pytest.mark.trio(pyfuncitem.obj)


_old_policy = asyncio.get_event_loop_policy()
_new_policy = trio_asyncio.TrioPolicy()
asyncio.set_event_loop_policy(_new_policy)


@pytest.fixture
def old_policy():
    asyncio.set_event_loop_policy(_old_policy)
    try:
        yield _old_policy
    finally:
        asyncio.set_event_loop_policy(_new_policy)
