import unittest
import pytest
import trio_asyncio
import asyncio
from trio.tests.asyncio import aiotest


class Seen:
    flag = 0


class CallTests(aiotest.TestCase):
    async def call_t_a(self, proc, *args, _scope=None):
        """called from Trio"""
        return await self.loop.call_asyncio(proc, *args, _scope=_scope)

    async def call_a_t(self, proc, *args):
        """call from asyncio to an async trio function"""
        return await self.loop.call_trio(proc, *args)

    def call_a_ts(self, proc, *args):
        """called from asyncio to a sync trio function"""
        return self.loop.call_trio_sync(proc, *args)

    def test_call_at(self):
        from trio_asyncio.loop import DeltaTime
        async def delay(t):
            done = asyncio.Event(loop=self.loop)
            self.loop.call_at(t, done.set)
            await done.wait()

        t = self.loop.time()+0.1
        assert isinstance(t,DeltaTime)
        self.loop.run_until_complete(delay(t))

    def test_asyncio_trio(self):
        """Call asyncio from trio"""

        async def dly_trio(seen):
            await trio.sleep(0.01)
            seen.flag |= 2
            return 8

        seen = Seen()
        res = self.loop.run_until_complete(self.call_a_t(dly_trio, seen))
        assert res == 8
        assert seen.flag == 2

    def test_asyncio_trio_sync(self):
        """Call asyncio from trio"""

        def dly_trio(seen):
            seen.flag |= 2
            return 8

        seen = Seen()
        res = self.loop.run_until_complete(self.call_a_ts(dly_trio, seen))
        assert res == 8
        assert seen.flag == 2

    def test_trio_asyncio(self):
        async def dly_asyncio(seen):
            await asyncio.sleep(0.01, loop=self.loop)
            seen.flag |= 1
            return 4

        seen = Seen()
        res = self.loop.run_task(self.call_t_a, dly_asyncio, seen)
        assert res == 4
        assert seen.flag == 1

    def test_asyncio_trio_error(self):
        async def err_trio():
            await trio.sleep(0.01)
            raise RuntimeError("I has another owie")

        with pytest.raises(RuntimeError) as err:
            res = self.loop.run_until_complete(self.call_a_t(err_trio))
        assert err.value.args[0] == "I has another owie"

    def test_asyncio_trio_sync_error(self):
        def err_trio_sync():
            t = self.loop.time() # verify that the loop is running
            raise RuntimeError("I has more owie")

        with pytest.raises(RuntimeError) as err:
            res = self.loop.run_until_complete(self.call_a_ts(err_trio_sync))
        assert err.value.args[0] == "I has more owie"

    def test_trio_asyncio_error(self):
        async def err_asyncio():
            await asyncio.sleep(0.01, loop=self.loop)
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            res = self.loop.run_task(self.call_t_a, err_asyncio)
        assert err.value.args[0] == "I has an owie"

    def test_asyncio_trio_cancel_out(self):
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
            res = self.loop.run_until_complete(
                self.call_a_t(cancelled_trio, seen)
            )
            pass
        assert seen.flag == 3

    def test_trio_asyncio_cancel_out(self):
        async def cancelled_asyncio(seen):
            seen.flag |= 1
            await asyncio.sleep(0.01, loop=self.loop)
            f = asyncio.Future(loop=self.loop)
            f.cancel()
            return f.result()  # raises error

        def cancelled_future(seen):
            seen.flag |= 1
            f = asyncio.Future(loop=self.loop)
            f.cancel()
            return f  # contains error

        async def check_cancel(proc, seen):
            with trio.open_cancel_scope() as scope:
                await self.call_t_a(proc, seen, _scope=scope)
            assert scope.cancel_called
            seen.flag |= 4

        seen = Seen()
        res = self.loop.run_task(check_cancel, cancelled_future, seen)
        assert seen.flag == 1 | 4

        seen = Seen()
        res = self.loop.run_task(check_cancel, cancelled_asyncio, seen)
        assert seen.flag == 1 | 4

    def test_asyncio_trio_cancel_in(self):
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
            started = asyncio.Event(loop=self.loop)
            f = asyncio.ensure_future(self.call_a_t(in_trio, started, seen))
            await started.wait()
            f.cancel()
            with pytest.raises(asyncio.CancelledError):
                await f
            seen.flag |= 8

        seen = Seen()
        res = self.loop.run_until_complete(cancel_asyncio(seen))
        assert seen.flag == 1 | 2 | 8

    def test_trio_asyncio_cancel_in(self):
        async def in_asyncio(started, seen):
            started.set()
            try:
                await asyncio.sleep(9999, loop=self.loop)
            except asyncio.CancelledError:
                seen.flag |= 1
            else:
                seen.flag |= 4
            finally:
                seen.flag |= 2

        async def cancel_trio(seen):
            started = trio.Event()
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self.call_t_a, in_asyncio, started, seen)
                await started.wait()
                nursery.cancel_scope.cancel()
            seen.flag |= 8

        seen = Seen()
        res = self.loop.run_task(cancel_trio, seen)
        assert seen.flag == 1 | 2 | 8


    def test_trio_asyncio_cancel_direct(self):
        def in_asyncio(started, seen):
            # This is intentionally not async
            seen.flag |= 1
            raise asyncio.CancelledError()

        async def cancel_trio(seen):
            started = trio.Event()
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self.call_t_a, in_asyncio, started, seen)
                await started.wait()
                nursery.cancel_scope.cancel()
            seen.flag |= 8

        seen = Seen()
        res = self.loop.run_task(cancel_trio, seen)
        assert seen.flag == 1 | 8


    def test_trio_asyncio_error_direct(self):
        def err_asyncio():
            # This is intentionally not async
            raise RuntimeError("I has an owie")

        with pytest.raises(RuntimeError) as err:
            res = self.loop.run_task(self.call_t_a, err_asyncio)
        assert err.value.args[0] == "I has an owie"

