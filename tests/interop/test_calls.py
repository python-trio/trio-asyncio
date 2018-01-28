import pytest
import trio_asyncio
import asyncio
import trio
from tests import aiotest
from functools import partial


class Seen:
    flag = 0


class TestCalls(aiotest.TestCase):
    async def call_t_a(self, proc, *args, loop=None):
        """called from Trio"""
        return await loop.run_asyncio(proc, *args)

    async def call_a_t(self, proc, *args, loop=None):
        """call from asyncio to an async trio function"""
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

        t = loop.time()+0.1
        await loop.run_asyncio(delay,t)

    @pytest.mark.trio
    async def test_asyncio_trio(self, loop):
        """Call asyncio from trio"""

        async def dly_trio(seen):
            await trio.sleep(0.01)
            seen.flag |= 2
            return 8

        seen = Seen()
        res = await loop.run_asyncio(partial(self.call_a_t, loop=loop),dly_trio, seen)
        assert res == 8
        assert seen.flag == 2

    @pytest.mark.trio
    async def test_asyncio_trio_sync(self, loop):
        """Call asyncio from trio"""

        def dly_trio(seen):
            seen.flag |= 2
            return 8

        seen = Seen()
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
    async def test_asyncio_trio_error(self, loop):
        async def err_trio():
            await trio.sleep(0.01)
            raise RuntimeError("I has another owie")

        with pytest.raises(RuntimeError) as err:
            res = await loop.run_asyncio(partial(self.call_a_t, loop=loop), err_trio)
        assert err.value.args[0] == "I has another owie"

    @pytest.mark.trio
    async def test_asyncio_trio_sync_error(self, loop):
        def err_trio_sync():
            t = loop.time() # verify that the loop is running
            raise RuntimeError("I has more owie")

        with pytest.raises(RuntimeError) as err:
            res = await loop.run_asyncio(partial(self.call_a_ts, loop=loop), err_trio_sync)
        assert err.value.args[0] == "I has more owie"

    @pytest.mark.trio
    async def test_trio_asyncio_error(self, loop):
        async def err_asyncio():
            await asyncio.sleep(0.01, loop=loop)
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            res = await self.call_t_a(err_asyncio, loop=loop)
        assert err.value.args[0] == "I has an owie"

    @pytest.mark.trio
    async def test_asyncio_trio_cancel_out(self, loop):
        async def cancelled_trio(seen):
            seen.flag |= 1
            await trio.sleep(0.01)
            scope = trio.hazmat.current_task()._cancel_stack[-1]
            scope.cancel()
            seen.flag |= 2
            await trio.sleep(0.01)
            seen.flag |= 4

        seen = Seen()
        with pytest.raises(asyncio.CancelledError) as err:
            res = await loop.run_asyncio(partial(self.call_a_t, loop=loop), cancelled_trio, seen)
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
            with trio.open_cancel_scope() as scope:
                with pytest.raises(asyncio.CancelledError):
                    await self.call_t_a(proc, seen, loop=loop)
            assert not scope.cancel_called
            seen.flag |= 4

        seen = Seen()
        res = await check_cancel(cancelled_future, seen)
        assert seen.flag == 1 | 4

        seen = Seen()
        res = await check_cancel(cancelled_asyncio, seen)
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
        res = await loop.run_asyncio(cancel_asyncio,seen)
        assert seen.flag == 1 | 2 | 8

    @pytest.mark.trio
    async def test_trio_asyncio_cancel_in(self, loop):
        async def in_asyncio(started, seen):
            started.set()
            try:
                await asyncio.sleep(9999, loop=loop)
            except asyncio.CancelledError:
                seen.flag |= 1
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
        res = await cancel_trio(seen)
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
                    nursery.start_soon(partial(self.call_t_a, loop=loop), in_asyncio, started, seen)
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
            res = await self.call_t_a(err_asyncio, loop=loop)
        assert err.value.args[0] == "I has an owie"

