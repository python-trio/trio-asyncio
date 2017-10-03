# XX this does not belong here -- b/c it's here, these things only apply to
# the tests in trio/_core/tests, not in trio/tests. For now there's some
# copy-paste...
#
# this stuff should become a proper pytest plugin

import pytest
import inspect

from trio._core.tests.conftest import trio_test, MockClock

import trio
import trio.asyncio
import asyncio

@pytest.fixture(scope="function", autouse=True)
def loop(request):

    loop = trio.asyncio.TrioEventLoop()
    request.instance.loop = loop
    asyncio.set_event_loop(loop)

    yield loop

    # check that the loop really is idle
#    if loop._q.qsize():
#        import pdb;pdb.set_trace()
#    assert loop._q.qsize() == 0
    assert not loop._timers
    assert not loop._delayed_calls
    if not loop.is_closed():
        loop.run_task(trio._core.wait_all_tasks_blocked)
        loop.close()

# FIXME: split off into a package (or just make part of trio's public
# interface?), with config file to enable? and I guess a mark option too; I
# guess it's useful with the class- and file-level marking machinery (where
# the raw @trio_test decorator isn't enough).
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = trio_test(pyfuncitem.obj)
