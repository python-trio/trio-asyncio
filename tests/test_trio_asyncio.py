import pytest
import sys
import types
import asyncio
import trio
import trio.testing
import trio_asyncio
import contextlib
import gc


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
async def test_exception_after_closed(caplog):
    async with trio_asyncio.open_loop() as loop:
        pass
    loop.call_exception_handler({"message": "Test exception after loop closed"})
    assert len(caplog.records) == 1
    assert caplog.records[0].message == "Test exception after loop closed"


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


@pytest.mark.trio
async def test_cancel_loop(autojump_clock):
    with trio.move_on_after(1) as scope:
        async with trio_asyncio.open_loop():
            await trio.sleep_forever()
    assert trio.current_time() == 1
    assert scope.cancelled_caught


@pytest.mark.trio
@pytest.mark.parametrize("shield", (False, True))
@pytest.mark.parametrize("body_raises", (False, True))
async def test_cancel_loop_with_tasks(autojump_clock, shield, body_raises):
    record = []

    if body_raises:
        catcher = trio.testing.RaisesGroup(
            trio.testing.Matcher(ValueError, match="hi"), flatten_subgroups=True
        )
    else:
        catcher = contextlib.nullcontext()

    with catcher, trio.move_on_after(1.25) as scope:
        async with trio_asyncio.open_loop():

            async def trio_task():
                try:
                    with trio.CancelScope(shield=shield):
                        await trio.sleep(1)
                finally:
                    record.append("trio_task done at")
                    record.append(trio.current_time())

            async def aio_task():
                await asyncio.sleep(1)
                try:
                    await trio_asyncio.trio_as_aio(trio_task)()
                except asyncio.CancelledError:
                    assert not shield
                    raise
                except trio.Cancelled:
                    assert False
                else:
                    assert shield
                finally:
                    record.append("aio_task done")

            try:
                async with trio.open_nursery() as nursery:
                    nursery.cancel_scope.shield = True

                    @nursery.start_soon
                    async def unshield_later():
                        await trio.sleep(1.5)
                        nursery.cancel_scope.shield = False

                    nursery.start_soon(trio_asyncio.aio_as_trio(aio_task))
                    if body_raises:
                        try:
                            await trio.sleep_forever()
                        finally:
                            raise ValueError("hi")
            finally:
                record.append("toplevel done")

    assert record == [
        "trio_task done at",
        trio.current_time(),
        "aio_task done",
        "toplevel done",
    ]
    assert trio.current_time() == 1.5 + (shield * 0.5)
    assert scope.cancelled_caught == (not shield)


@pytest.mark.trio
async def test_executor_limiter_deadlock():
    def noop():
        pass

    # capacity of 1 to catch a double-acquire
    limiter = trio.CapacityLimiter(1)
    executor = trio_asyncio.TrioExecutor(limiter=limiter)
    async with trio_asyncio.open_loop() as loop:
        with trio.move_on_after(1) as scope:
            await trio_asyncio.aio_as_trio(loop.run_in_executor)(executor, noop)

    assert not scope.cancelled_caught


def test_system_exit():
    async def main():
        raise SystemExit(42)

    with pytest.raises(SystemExit) as scope:
        asyncio.run(main())

    assert scope.value.code == 42


@pytest.mark.trio
@pytest.mark.parametrize("alive_on_exit", (False, True))
@pytest.mark.parametrize("slow_finalizer", (False, True))
@pytest.mark.parametrize("loop_timeout", (0, 1, 20))
async def test_asyncgens(alive_on_exit, slow_finalizer, loop_timeout, autojump_clock):
    import sniffio

    record = set()
    holder = []

    async def agen(label, extra):
        assert sniffio.current_async_library() == label
        if label == "asyncio":
            loop = asyncio.get_running_loop()
        try:
            yield 1
        finally:
            library = sniffio.current_async_library()
            if label == "asyncio":
                assert loop is asyncio.get_running_loop()
            try:
                await sys.modules[library].sleep(5 if slow_finalizer else 0)
            except (trio.Cancelled, asyncio.CancelledError):
                pass
            record.add((label + extra, library))

    async def iterate_one(label, extra=""):
        ag = agen(label, extra)
        await ag.asend(None)
        if alive_on_exit:
            holder.append(ag)
        else:
            del ag

    sys.unraisablehook, prev_hook = sys.__unraisablehook__, sys.unraisablehook
    try:
        before_hooks = sys.get_asyncgen_hooks()

        start_time = trio.current_time()
        with trio.move_on_after(loop_timeout) as scope:
            if loop_timeout == 0:
                scope.cancel()
            async with trio_asyncio.open_loop() as loop, trio_asyncio.open_loop() as loop2:
                assert sys.get_asyncgen_hooks() != before_hooks
                async with trio.open_nursery() as nursery:
                    # Make sure the iterate_one aio tasks don't get
                    # cancelled before they start:
                    nursery.cancel_scope.shield = True
                    try:
                        nursery.start_soon(iterate_one, "trio")
                        nursery.start_soon(
                            loop.run_aio_coroutine, iterate_one("asyncio")
                        )
                        nursery.start_soon(
                            loop2.run_aio_coroutine, iterate_one("asyncio", "2")
                        )
                        await loop.synchronize()
                        await loop2.synchronize()
                    finally:
                        nursery.cancel_scope.shield = False
                if not alive_on_exit and sys.implementation.name == "pypy":
                    for _ in range(5):
                        gc.collect()

        # Make sure we cleaned up properly once all trio-aio loops were closed
        assert sys.get_asyncgen_hooks() == before_hooks

        # asyncio agens should be finalized as soon as asyncio loop ends,
        # regardless of liveness
        assert ("asyncio", "asyncio") in record
        assert ("asyncio2", "asyncio") in record

        # asyncio agen finalizers should be able to take a cancel
        if (slow_finalizer or loop_timeout == 0) and alive_on_exit:
            # Each loop finalizes in series, and takes 5 seconds
            # if slow_finalizer is true.
            assert trio.current_time() == start_time + min(loop_timeout, 10)
            assert scope.cancelled_caught == (loop_timeout < 10)
        else:
            # `not alive_on_exit` implies that the asyncio agen aclose() tasks
            # are started before loop shutdown, which means they'll be
            # cancelled during loop shutdown; this matches regular asyncio.
            #
            # `not slow_finalizer and loop_timeout > 0` implies that the agens
            # have time to complete before we cancel them.
            assert trio.current_time() == start_time
            assert not scope.cancelled_caught

        # trio asyncgen should eventually be finalized in trio mode
        del holder[:]
        for _ in range(5):
            gc.collect()
        await trio.testing.wait_all_tasks_blocked()
        assert record == {
            ("trio", "trio"),
            ("asyncio", "asyncio"),
            ("asyncio2", "asyncio"),
        }
    finally:
        sys.unraisablehook = prev_hook
