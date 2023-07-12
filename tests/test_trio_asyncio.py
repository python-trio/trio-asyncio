import pytest
import sys
import types
import asyncio
import trio
import trio_asyncio


async def use_asyncio():
    await trio_asyncio.aio_as_trio(asyncio.sleep)(0)


@pytest.fixture()
async def asyncio_fixture_with_fixtured_loop(loop):
    await use_asyncio()
    yield None


@pytest.fixture()
async def asyncio_fixture_own_loop():
    async with trio_asyncio.open_loop():
        await use_asyncio()
        yield None


@pytest.mark.trio
async def test_no_fixture():
    async with trio_asyncio.open_loop():
        await use_asyncio()


@pytest.mark.trio
async def test_half_fixtured_asyncpg_conn(asyncio_fixture_own_loop):
    await use_asyncio()


@pytest.mark.trio
async def test_fixtured_asyncpg_conn(asyncio_fixture_with_fixtured_loop):
    await use_asyncio()


@pytest.mark.trio
async def test_get_running_loop():
    async with trio_asyncio.open_loop() as loop:
        assert asyncio.get_running_loop() == loop


@pytest.mark.trio
async def test_tasks_get_cancelled():
    record = []
    tasks = []

    @types.coroutine
    def aio_yield():
        yield

    async def aio_sleeper(key):
        try:
            await asyncio.sleep(10)
            record.append("expired")
        finally:
            try:
                # Prove that we're still running in the aio loop, not
                # some GC pass
                await aio_yield()
            finally:
                record.append(key)
                if "early" in key:
                    tasks.append(asyncio.ensure_future(aio_sleeper("aio late")))
                    asyncio.get_event_loop().run_trio_task(trio_sleeper, "trio late")

    async def trio_sleeper(key):
        try:
            await trio.sleep_forever()
        finally:
            await trio.lowlevel.cancel_shielded_checkpoint()
            record.append(key)

    async with trio_asyncio.open_loop() as loop:
        tasks.append(asyncio.ensure_future(aio_sleeper("aio early")))
        loop.run_trio_task(trio_sleeper, "trio early")

    assert set(record) == {"aio early", "trio early", "trio late"}
    assert len(tasks) == 2 and tasks[0].done() and not tasks[1].done()

    # Suppress "Task was destroyed but it was pending!" message
    tasks[1]._log_traceback = False
    tasks[1]._log_destroy_pending = False

    # Suppress the "coroutine ignored GeneratorExit" message
    while True:
        try:
            tasks[1]._coro.throw(SystemExit)
        except SystemExit:
            break
