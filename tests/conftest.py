# XX this does not belong here -- b/c it's here, these things only apply to
# the tests in trio/_core/tests, not in trio/tests. For now there's some
# copy-paste...
#
# this stuff should become a proper pytest plugin

import pytest
import inspect
import asyncio
import trio_asyncio

@pytest.fixture(scope="function", autouse=True)
async def loop(request,nursery):
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


# FIXME: split off into a package (or just make part of trio's public
# interface?), with config file to enable? and I guess a mark option too; I
# guess it's useful with the class- and file-level marking machinery (where
# the raw @trio_test decorator isn't enough).
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = pytest.mark.trio(pyfuncitem.obj)
