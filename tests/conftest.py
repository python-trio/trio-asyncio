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
if not hasattr(asyncio,'current_task'):
    def current_task(loop=None):
        return asyncio.Task.current_task(loop)
    asyncio.current_task = current_task

if not hasattr(asyncio,'all_tasks'):
    def all_tasks(loop=None):
        return asyncio.Task.all_tasks(loop)
    asyncio.all_tasks = all_tasks

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

