import pytest
import asyncio
import trio
import sniffio
from trio_asyncio import aio_as_trio, trio_as_aio
from tests import aiotest
from functools import partial
import sys
from .. import utils as test_utils


class Seen:
    flag = 0


async def async_gen_to_list(generator):
    result = []
    async for item in generator:
        result.append(item)
    return result


class TrioContext:
    def __init__(self, parent):
        self.parent = parent

    async def __aenter__(self):
        assert self.parent.did_it == 0
        self.parent.did_it = 1
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "trio"
        await trio.sleep(0.01)
        self.parent.did_it = 2
        return self

    async def __aexit__(self, *tb):
        assert self.parent.did_it == 3
        self.parent.did_it = 4


class AioContext:
    def __init__(self, parent, loop):
        self.parent = parent
        self.loop = loop

    async def __aenter__(self):
        assert self.parent.did_it == 0
        self.parent.did_it = 1
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01, loop=self.loop)
        self.parent.did_it = 2
        return self

    async def __aexit__(self, *tb):
        assert self.parent.did_it == 3
        self.parent.did_it = 4


class TestCalls(aiotest.TestCase):
    async def call_t_a(self, proc, *args, loop=None):
        """called from Trio"""
        return await aio_as_trio(proc, loop=loop)(*args)

    async def call_t_a_depr(self, proc, *args, loop=None):
        """called from Trio"""
        with test_utils.deprecate(self):
            return await loop.run_asyncio(proc, *args)

    async def call_a_t(self, proc, *args, loop=None):
        """call from asyncio to an async trio function"""
        return await trio_as_aio(proc, loop=loop)(*args)

    async def call_a_t_depr(self, proc, *args, loop=None):
        """call from asyncio to an async trio function"""
        with test_utils.deprecate(self):
            return await loop.run_trio(proc, *args)

    async def call_a_ts(self, proc, *args, loop=None):
        """called from asyncio to a sync trio function"""
        return proc(*args)

    @pytest.mark.trio
    async def test_call_at(self, loop):
        async def delay(t):
            done = asyncio.Event(loop=loop)
            loop.call_at(t, done.set)
            await done.wait()

        t = loop.time() + 0.1
        await aio_as_trio(delay, loop=loop)(t)

    @pytest.mark.trio
    async def test_call_at_depr(self, loop):
        async def delay(t):
            done = asyncio.Event(loop=loop)
            loop.call_at(t, done.set)
            await done.wait()

        t = loop.time() + 0.1
        with test_utils.deprecate(self):
            await loop.run_asyncio(delay, t)

    @pytest.mark.trio
    async def test_asyncio_trio(self, loop):
        """Call asyncio from trio"""

        async def dly_trio(seen):
            await trio.sleep(0.01)
            seen.flag |= 2
            return 8

        seen = Seen()
        res = await aio_as_trio(partial(self.call_a_t, loop=loop), loop=loop)(dly_trio, seen)
        assert res == 8
        assert seen.flag == 2

    @pytest.mark.trio
    async def test_asyncio_trio_depr(self, loop):
        """Call asyncio from trio"""

        async def dly_trio(seen):
            await trio.sleep(0.01)
            seen.flag |= 2
            return 8

        seen = Seen()
        res = await aio_as_trio(partial(self.call_a_t_depr, loop=loop), loop=loop)(dly_trio, seen)
        assert res == 8
        assert seen.flag == 2

    @pytest.mark.trio
    async def test_call_asyncio_ctx(self, loop):
        self.did_it = 0
        async with aio_as_trio(AioContext(self, loop), loop=loop) as ctx:
            assert ctx.parent is self
            assert self.did_it == 2
            self.did_it = 3
        assert self.did_it == 4

    @pytest.mark.trio
    async def test_call_trio_ctx(self, loop):
        async def _call_trio_ctx():
            self.did_it = 0
            async with trio_as_aio(TrioContext(self)) as ctx:
                assert ctx.parent is self
                assert self.did_it == 2
                self.did_it = 3
            assert self.did_it == 4

        await aio_as_trio(_call_trio_ctx, loop=loop)()

    @pytest.mark.trio
    async def test_call_trio_ctx_depr(self, loop):
        async def _call_trio_ctx():
            self.did_it = 0
            async with loop.wrap_trio_context(TrioContext(self)) as ctx:
                assert ctx.parent is self
                assert self.did_it == 2
                self.did_it = 3
            assert self.did_it == 4

        with test_utils.deprecate(self):
            await loop.run_asyncio(_call_trio_ctx)

    @pytest.mark.trio
    async def test_asyncio_trio_sync(self, loop):
        """Call asyncio from trio"""

        def dly_trio(seen):
            seen.flag |= 2
            return 8

        seen = Seen()
        res = await aio_as_trio(partial(self.call_a_ts, loop=loop), loop=loop)(dly_trio, seen)
        assert res == 8
        assert seen.flag == 2

    @pytest.mark.trio
    async def test_asyncio_trio_sync_depr(self, loop):
        """Call asyncio from trio"""

        def dly_trio(seen):
            seen.flag |= 2
            return 8

        seen = Seen()
        with test_utils.deprecate(self):
            res = await loop.run_asyncio(partial(self.call_a_ts, loop=loop), dly_trio, seen)
        assert res == 8
        assert seen.flag == 2

    @pytest.mark.trio
    async def test_trio_asyncio(self, loop):
        async def dly_asyncio(seen):
            await asyncio.sleep(0.01, loop=loop)
            seen.flag |= 1
            return 4

        seen = Seen()
        res = await self.call_t_a(dly_asyncio, seen, loop=loop)
        assert res == 4
        assert seen.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_depr(self, loop):
        async def dly_asyncio(seen):
            await asyncio.sleep(0.01, loop=loop)
            seen.flag |= 1
            return 4

        seen = Seen()
        res = await self.call_t_a_depr(dly_asyncio, seen, loop=loop)
        assert res == 4
        assert seen.flag == 1

    @pytest.mark.trio
    async def test_asyncio_trio_error(self, loop):
        async def err_trio():
            await trio.sleep(0.01)
            raise RuntimeError("I has another owie")

        with pytest.raises(RuntimeError) as err:
            await aio_as_trio(partial(self.call_a_t, loop=loop), loop=loop)(err_trio)
        assert err.value.args[0] == "I has another owie"

    @pytest.mark.trio
    async def test_asyncio_trio_error_depr1(self, loop):
        async def err_trio():
            await trio.sleep(0.01)
            raise RuntimeError("I has another owie")

        with pytest.raises(RuntimeError) as err:
            await aio_as_trio(partial(self.call_a_t_depr, loop=loop), loop=loop)(err_trio)
        assert err.value.args[0] == "I has another owie"

    @pytest.mark.trio
    async def test_asyncio_trio_error_depr2(self, loop):
        async def err_trio():
            await trio.sleep(0.01)
            raise RuntimeError("I has another owie")

        with pytest.raises(RuntimeError) as err:
            with test_utils.deprecate(self):
                await loop.run_asyncio(partial(self.call_a_t, loop=loop), err_trio)
        assert err.value.args[0] == "I has another owie"

    @pytest.mark.trio
    async def test_asyncio_trio_error_depr3(self, loop):
        async def err_trio():
            await trio.sleep(0.01)
            raise RuntimeError("I has another owie")

        with pytest.raises(RuntimeError) as err:
            with test_utils.deprecate(self):
                await loop.run_asyncio(partial(self.call_a_t_depr, loop=loop), err_trio)
        assert err.value.args[0] == "I has another owie"

    @pytest.mark.trio
    async def test_asyncio_trio_sync_error(self, loop):
        def err_trio_sync():
            loop.time()  # verify that the loop is running
            raise RuntimeError("I has more owie")

        with pytest.raises(RuntimeError) as err:
            await aio_as_trio(partial(self.call_a_ts, loop=loop), loop=loop)(err_trio_sync)
        assert err.value.args[0] == "I has more owie"

    @pytest.mark.trio
    async def test_asyncio_trio_sync_error_depr(self, loop):
        def err_trio_sync():
            loop.time()  # verify that the loop is running
            raise RuntimeError("I has more owie")

        with pytest.raises(RuntimeError) as err:
            with test_utils.deprecate(self):
                await loop.run_asyncio(partial(self.call_a_ts, loop=loop), err_trio_sync)
        assert err.value.args[0] == "I has more owie"

    @pytest.mark.trio
    async def test_trio_asyncio_error(self, loop):
        async def err_asyncio():
            await asyncio.sleep(0.01, loop=loop)
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            await self.call_t_a(err_asyncio, loop=loop)
        assert err.value.args[0] == "I has an owie"

    @pytest.mark.trio
    async def test_trio_asyncio_error_depr(self, loop):
        async def err_asyncio():
            await asyncio.sleep(0.01, loop=loop)
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            await self.call_t_a_depr(err_asyncio, loop=loop)
        assert err.value.args[0] == "I has an owie"

    @pytest.mark.trio
    async def test_asyncio_trio_cancel_out(self, loop):
        async def cancelled_trio(seen):
            seen.flag |= 1
            await trio.sleep(0.01)
            scope = trio.lowlevel.current_task()._cancel_status._scope
            scope.cancel()
            seen.flag |= 2
            await trio.sleep(0.01)
            seen.flag |= 4

        seen = Seen()
        with pytest.raises(asyncio.CancelledError):
            await aio_as_trio(partial(self.call_a_t, loop=loop), loop=loop)(cancelled_trio, seen)
        assert seen.flag == 3

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_out(self, loop):
        async def cancelled_asyncio(seen):
            seen.flag |= 1
            await asyncio.sleep(0.01, loop=loop)
            f = asyncio.Future(loop=loop)
            f.cancel()
            return f.result()  # raises error

        def cancelled_future(seen):
            seen.flag |= 1
            f = asyncio.Future(loop=loop)
            f.cancel()
            return f  # contains error

        async def check_cancel(proc, seen):
            with trio.CancelScope() as scope:
                with pytest.raises(asyncio.CancelledError):
                    await self.call_t_a(proc, seen, loop=loop)
            assert not scope.cancel_called
            seen.flag |= 4

        seen = Seen()
        await check_cancel(cancelled_future, seen)
        assert seen.flag == 1 | 4

        seen = Seen()
        await check_cancel(cancelled_asyncio, seen)
        assert seen.flag == 1 | 4

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_out_depr(self, loop):
        async def cancelled_asyncio(seen):
            seen.flag |= 1
            await asyncio.sleep(0.01, loop=loop)
            f = asyncio.Future(loop=loop)
            f.cancel()
            return f.result()  # raises error

        def cancelled_future(seen):
            seen.flag |= 1
            f = asyncio.Future(loop=loop)
            f.cancel()
            return f  # contains error

        async def check_cancel(proc, seen):
            with trio.CancelScope() as scope:
                with pytest.raises(asyncio.CancelledError):
                    await self.call_t_a_depr(proc, seen, loop=loop)
            assert not scope.cancel_called
            seen.flag |= 4

        seen = Seen()
        await check_cancel(cancelled_future, seen)
        assert seen.flag == 1 | 4

        seen = Seen()
        await check_cancel(cancelled_asyncio, seen)
        assert seen.flag == 1 | 4

    @pytest.mark.trio
    async def test_asyncio_trio_cancel_in(self, loop):
        async def in_trio(started, seen):
            started.set()
            try:
                await trio.sleep(1)
            except trio.Cancelled:
                seen.flag |= 1
            else:
                seen.flag |= 4
            finally:
                seen.flag |= 2

        async def cancel_asyncio(seen):
            started = asyncio.Event(loop=loop)
            f = asyncio.ensure_future(self.call_a_t(in_trio, started, seen, loop=loop))
            await started.wait()
            f.cancel()
            with pytest.raises(asyncio.CancelledError):
                await f
            seen.flag |= 8

        seen = Seen()
        await aio_as_trio(cancel_asyncio, loop=loop)(seen)
        assert seen.flag == 1 | 2 | 8

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_in(self, loop):
        async def in_asyncio(started, seen):
            started.set()
            try:
                await asyncio.sleep(9999, loop=loop)
            except asyncio.CancelledError:
                seen.flag |= 1
            except trio.Cancelled:
                seen.flag |= 16
            else:
                seen.flag |= 4
            finally:
                seen.flag |= 2

        async def cancel_trio(seen):
            started = trio.Event()
            async with trio.open_nursery() as nursery:
                nursery.start_soon(partial(self.call_t_a, loop=loop), in_asyncio, started, seen)
                await started.wait()
                nursery.cancel_scope.cancel()
            seen.flag |= 8

        seen = Seen()
        await cancel_trio(seen)
        assert seen.flag == 1 | 2 | 8

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_in_depr(self, loop):
        async def in_asyncio(started, seen):
            started.set()
            try:
                await asyncio.sleep(9999, loop=loop)
            except asyncio.CancelledError:
                seen.flag |= 1
            except trio.Cancelled:
                seen.flag |= 16
            else:
                seen.flag |= 4
            finally:
                seen.flag |= 2

        async def cancel_trio(seen):
            started = trio.Event()
            async with trio.open_nursery() as nursery:
                nursery.start_soon(
                    partial(self.call_t_a_depr, loop=loop), in_asyncio, started, seen
                )
                await started.wait()
                nursery.cancel_scope.cancel()
            seen.flag |= 8

        seen = Seen()
        await cancel_trio(seen)
        assert seen.flag == 1 | 2 | 8

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_direct(self, loop):
        def in_asyncio(started, seen):
            # This is intentionally not async
            seen.flag |= 1
            raise asyncio.CancelledError()

        async def cancel_trio(seen):
            started = trio.Event()
            try:
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(
                        partial(self.call_t_a, loop=loop), in_asyncio, started, seen
                    )
                    await started.wait()
                    nursery.cancel_scope.cancel()
            finally:
                seen.flag |= 8

        seen = Seen()
        with pytest.raises(asyncio.CancelledError):
            await cancel_trio(seen)
        assert seen.flag == 1 | 8

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_direct_depr(self, loop):
        def in_asyncio(started, seen):
            # This is intentionally not async
            seen.flag |= 1
            raise asyncio.CancelledError()

        async def cancel_trio(seen):
            started = trio.Event()
            try:
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(
                        partial(self.call_t_a_depr, loop=loop), in_asyncio, started, seen
                    )
                    await started.wait()
                    nursery.cancel_scope.cancel()
            finally:
                seen.flag |= 8

        seen = Seen()
        with pytest.raises(asyncio.CancelledError):
            await cancel_trio(seen)
        assert seen.flag == 1 | 8

    @pytest.mark.trio
    async def test_trio_asyncio_error_direct(self, loop):
        def err_asyncio():
            # This is intentionally not async
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            await self.call_t_a(err_asyncio, loop=loop)
        assert err.value.args[0] == "I has an owie"

    @pytest.mark.trio
    async def test_trio_asyncio_error_direct_depr(self, loop):
        def err_asyncio():
            # This is intentionally not async
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            await self.call_t_a_depr(err_asyncio, loop=loop)
        assert err.value.args[0] == "I has an owie"

    @pytest.mark.trio
    async def test_trio_asyncio_generator(self, loop):
        async def dly_asyncio():
            yield 1
            await asyncio.sleep(0.01, loop=loop)
            yield 2

        with test_utils.deprecate(self):
            res = await async_gen_to_list(loop.wrap_generator(dly_asyncio))
        assert res == [1, 2]

    @pytest.mark.trio
    async def test_trio_asyncio_generator_with_error(self, loop):
        async def dly_asyncio():
            yield 1
            raise RuntimeError("I has an owie")
            yield 2

        with test_utils.deprecate(self):
            with pytest.raises(RuntimeError) as err:
                await async_gen_to_list(loop.wrap_generator(dly_asyncio))
        assert err.value.args[0] == "I has an owie"

    @pytest.mark.trio
    async def test_trio_asyncio_generator_with_cancellation(self, loop):
        async def dly_asyncio(hold, seen):
            yield 1
            seen.flag |= 1
            await hold.wait()

        async def cancel_soon(nursery):
            await trio.sleep(0.01)
            nursery.cancel_scope.cancel()

        hold = asyncio.Event(loop=loop)
        seen = Seen()

        with test_utils.deprecate(self):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(async_gen_to_list, loop.wrap_generator(dly_asyncio, hold, seen))
                nursery.start_soon(cancel_soon, nursery)
        assert nursery.cancel_scope.cancel_called
        assert seen.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_iterator(self, loop):
        async def slow_nums():
            for n in range(1, 6):
                await asyncio.sleep(0.01, loop=loop)
                yield n

        sum = 0
        async for n in aio_as_trio(slow_nums()):
            sum += n
        assert sum == 15

    @pytest.mark.trio
    async def test_trio_asyncio_iterator_depr(self, loop):
        async def slow_nums():
            for n in range(1, 6):
                await asyncio.sleep(0.01, loop=loop)
                yield n

        sum = 0
        # with test_utils.deprecate(self): ## not yet
        async for n in aio_as_trio(
            slow_nums(), loop=loop
        ):
            sum += n
        assert sum == 15
