import pytest
import trio_asyncio
import asyncio
import trio
import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup, BaseExceptionGroup


class Seen:
    flag = 0


class TestMisc:
    @pytest.mark.trio
    async def test_close_no_stop(self):
        async with trio_asyncio.open_loop() as loop:
            triggered = trio.Event()

            def close_no_stop():
                with pytest.raises(RuntimeError):
                    loop.close()
                triggered.set()

            loop.call_soon(close_no_stop)
            await triggered.wait()

    @pytest.mark.trio
    async def test_too_many_stops(self):
        with trio.move_on_after(1) as scope:
            async with trio_asyncio.open_loop() as loop:
                await trio.lowlevel.checkpoint()
                loop.stop()
        assert (
            not scope.cancelled_caught
        ), "Possible deadlock after manual call to loop.stop"

    @pytest.mark.trio
    async def test_err1(self, loop):
        async def raise_err():
            raise RuntimeError("Foo")

        with pytest.raises(RuntimeError) as err:
            await trio_asyncio.aio_as_trio(raise_err, loop=loop)()
        assert err.value.args[0] == "Foo"

    @pytest.mark.trio
    async def test_err3(self, loop):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1
            raise RuntimeError("Hello")

        async def call_nested():
            with pytest.raises(RuntimeError) as err:
                await trio_asyncio.trio_as_aio(nest, loop=loop)()
            assert err.value.args[0] == "Hello"

        await trio_asyncio.aio_as_trio(call_nested, loop=loop)()
        assert owch

    @pytest.mark.trio
    async def test_run(self, loop):
        owch = 0

        async def nest():
            await trio.sleep(0.01)
            nonlocal owch
            owch = 1

        async def call_nested():
            await trio_asyncio.trio_as_aio(nest, loop=loop)()

        await trio_asyncio.aio_as_trio(call_nested, loop=loop)()
        assert owch

    async def _test_run(self):
        owch = 0

        async def nest():
            await trio.sleep(0.01)
            nonlocal owch
            owch = 1

        async def call_nested():
            await trio_asyncio.trio_as_aio(nest)()

        await trio_asyncio.aio_as_trio(call_nested)()
        assert owch

    def test_run2(self):
        trio_asyncio.run(self._test_run)

    @pytest.mark.trio
    async def test_run_task(self):
        owch = 0

        async def nest(x):
            nonlocal owch
            owch += x

        with pytest.raises(RuntimeError):
            trio_asyncio.run_trio_task(nest, 100)

        with pytest.raises((AttributeError, RuntimeError, TypeError)):
            with trio_asyncio.open_loop():
                nest(1000)

        async with trio_asyncio.open_loop():
            trio_asyncio.run_trio_task(nest, 1)
        await trio.sleep(0.05)
        assert owch == 1

    @pytest.mark.trio
    async def test_err2(self, loop):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1
            raise RuntimeError("Hello")

        async def call_nested():
            await trio_asyncio.aio_as_trio(nest, loop=loop)()

        async def call_more_nested():
            with pytest.raises(RuntimeError) as err:
                await trio_asyncio.trio_as_aio(call_nested, loop=loop)()
            assert err.value.args[0] == "Hello"

        await trio_asyncio.aio_as_trio(call_more_nested, loop=loop)()
        assert owch

    @pytest.mark.trio
    async def test_run3(self, loop):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1

        async def call_nested():
            await trio_asyncio.aio_as_trio(nest, loop=loop)()

        async def call_more_nested():
            await trio_asyncio.trio_as_aio(call_nested, loop=loop)()

        await trio_asyncio.aio_as_trio(call_more_nested, loop=loop)()
        assert owch

    @pytest.mark.trio
    async def test_cancel_sleep(self, loop):
        owch = 0

        def do_not_run():
            nonlocal owch
            owch = 1

        async def cancel_sleep():
            h = loop.call_later(0.2, do_not_run)
            await asyncio.sleep(0.01)
            h.cancel()
            await asyncio.sleep(0.3)

        await trio_asyncio.aio_as_trio(cancel_sleep, loop=loop)()
        assert owch == 0


@pytest.mark.trio
async def test_wrong_context_manager_order():
    take_down = trio.Event()

    async def work_in_asyncio():
        await asyncio.sleep(0)

    async def runner(*, task_status=trio.TASK_STATUS_IGNORED):
        await trio_asyncio.aio_as_trio(work_in_asyncio)()
        try:
            task_status.started()
            await take_down.wait()
        finally:
            await trio_asyncio.aio_as_trio(work_in_asyncio)()

    async with trio.open_nursery() as nursery:
        async with trio_asyncio.open_loop():
            await nursery.start(runner)
            take_down.set()


@pytest.mark.trio
@pytest.mark.skipif(sys.platform == "win32", reason="Not supported on Windows")
async def test_keyboard_interrupt_teardown():
    asyncio_loop_closed = trio.Event()

    async def work_in_trio_no_matter_what(*, task_status=trio.TASK_STATUS_IGNORED):
        await trio_asyncio.aio_as_trio(work_in_asyncio)()
        try:
            # KeyboardInterrupt won't cancel this coroutine thanks to the shield
            with trio.CancelScope(shield=True):
                task_status.started()
                await asyncio_loop_closed.wait()
        finally:
            # Hence this call will be exceuted after run_asyncio_loop is cancelled
            with pytest.raises(RuntimeError):
                await trio_asyncio.aio_as_trio(work_in_asyncio)()

    async def work_in_asyncio():
        await asyncio.sleep(0)

    async def run_asyncio_loop(nursery, *, task_status=trio.TASK_STATUS_IGNORED):
        with trio.CancelScope() as cancel_scope:
            try:
                async with trio_asyncio.open_loop():
                    # Starting a coroutine from here make it inherit the access
                    # to the asyncio loop context manager
                    await nursery.start(work_in_trio_no_matter_what)
                    task_status.started(cancel_scope)
                    await trio.sleep_forever()
            finally:
                asyncio_loop_closed.set()

    import signal
    import threading

    with pytest.raises(KeyboardInterrupt):
        async with trio.open_nursery() as nursery:
            await nursery.start(run_asyncio_loop, nursery)
            # Trigger KeyboardInterrupt that should propagate accross the coroutines
            signal.pthread_kill(threading.get_ident(), signal.SIGINT)


@pytest.mark.trio
@pytest.mark.parametrize("throw_another", [False, True])
async def test_cancel_loop(throw_another):
    """Regression test for #76: ensure that cancelling a trio-asyncio loop
    does not cause any of the tasks running within it to yield a
    result of Cancelled.
    """

    async def manage_loop(task_status):
        try:
            with trio.CancelScope() as scope:
                async with trio_asyncio.open_loop() as loop:
                    task_status.started((loop, scope))
                    await trio.sleep_forever()
        finally:
            assert scope.cancelled_caught

    # Trio-flavored async function. Runs as a trio-aio loop task
    # and gets cancelled when the loop does.
    async def trio_task():
        async with trio.open_nursery() as nursery:
            nursery.start_soon(trio.sleep_forever)
            try:
                await trio.sleep_forever()
            except trio.Cancelled:
                if throw_another:
                    # This will combine with the Cancelled from the
                    # background sleep_forever task to create an
                    # ExceptionGroup escaping from trio_task
                    raise ValueError("hi")

    async with trio.open_nursery() as nursery:
        loop, scope = await nursery.start(manage_loop)
        fut = loop.trio_as_future(trio_task)
        await trio.testing.wait_all_tasks_blocked()
        scope.cancel()
    assert fut.done()
    if throw_another:
        with pytest.raises(ValueError, match="hi"):
            fut.result()
    else:
        assert fut.cancelled()


@pytest.mark.trio
async def test_trio_as_fut_throws_after_cancelled():
    """If a trio_as_future() future is cancelled, any exception
    thrown by the Trio task as it unwinds is still propagated.
    """

    async def trio_task():
        try:
            await trio.sleep_forever()
        finally:
            raise ValueError("hi")

    async with trio_asyncio.open_loop() as loop:
        fut = loop.trio_as_future(trio_task)
        await trio.testing.wait_all_tasks_blocked()
        fut.cancel()
        with pytest.raises(ValueError):
            await trio_asyncio.run_aio_future(fut)


@pytest.mark.trio
async def test_run_trio_task_errors(monkeypatch):
    async with trio_asyncio.open_loop() as loop:
        # Test never getting to start the task
        handle = loop.run_trio_task(trio.sleep_forever)
        handle.cancel()

        # Test cancelling the task
        handle = loop.run_trio_task(trio.sleep_forever)
        await trio.testing.wait_all_tasks_blocked()
        handle.cancel()

    # Helper for the rest of this test, which covers cases where
    # the Trio task raises an exception
    async def raise_in_aio_loop(exc):
        async def raise_it():
            raise exc

        async with trio_asyncio.open_loop() as loop:
            loop.run_trio_task(raise_it)

    # We temporarily modify the default exception handler to collect
    # the exceptions instead of logging or raising them

    exceptions = []

    def collect_exceptions(loop, context):
        if context.get("exception"):
            exceptions.append(context["exception"])
        else:
            exceptions.append(RuntimeError(context.get("message") or "unknown"))

    monkeypatch.setattr(
        trio_asyncio.TrioEventLoop, "default_exception_handler", collect_exceptions
    )
    expected = [ValueError("hi"), ValueError("lo"), KeyError(), IndexError()]
    await raise_in_aio_loop(expected[0])
    with pytest.raises(SystemExit):
        await raise_in_aio_loop(SystemExit(0))
    with pytest.raises(BaseExceptionGroup) as result:
        await raise_in_aio_loop(BaseExceptionGroup("", [expected[1], SystemExit()]))
    assert len(result.value.exceptions) == 1
    assert isinstance(result.value.exceptions[0], SystemExit)
    await raise_in_aio_loop(ExceptionGroup("", expected[2:]))

    assert len(exceptions) == 3
    assert exceptions[0] is expected[0]
    assert isinstance(exceptions[1], ExceptionGroup)
    assert exceptions[1].exceptions == (expected[1],)
    assert isinstance(exceptions[2], ExceptionGroup)
    assert exceptions[2].exceptions == tuple(expected[2:])


@pytest.mark.trio
async def test_contextvars():
    import contextvars

    cvar = contextvars.ContextVar("test_cvar")
    cvar.set("outer")

    async def fudge_in_aio():
        assert cvar.get() == "outer"
        cvar.set("middle")
        await trio_asyncio.trio_as_aio(fudge_in_trio)()
        assert cvar.get() == "middle"

    async def fudge_in_trio():
        assert cvar.get() == "middle"
        cvar.set("inner")

    async with trio_asyncio.open_loop() as loop:
        await trio_asyncio.aio_as_trio(fudge_in_aio)()
        assert cvar.get() == "outer"
