import pytest
from trio_asyncio import aio_as_trio, trio_as_aio, allow_asyncio
import asyncio
import trio
import sniffio
from tests import aiotest
import sys
import warnings
from contextlib import asynccontextmanager
from trio_asyncio import TrioAsyncioDeprecationWarning


def de_deprecate_converter(func):
    def wrapper(proc):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TrioAsyncioDeprecationWarning)
            return func(proc)

    return wrapper


class SomeThing:
    flag = 0

    def __init__(self, loop):
        self.loop = loop

    async def dly_trio(self):
        assert sniffio.current_async_library() == "trio"
        await trio.sleep(0.01)
        self.flag |= 2
        return 8

    @trio_as_aio
    async def dly_trio_adapted(self):
        assert sniffio.current_async_library() == "trio"
        await trio.sleep(0.01)
        self.flag |= 2
        return 8

    @aio_as_trio
    async def dly_asyncio_adapted(self):
        assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01)
        self.flag |= 1
        return 4

    async def dly_asyncio(self, do_test=True):
        if do_test:
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01)
        self.flag |= 1
        return 4

    async def iter_asyncio(self, do_test=True):
        if do_test:
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01)
        yield 1
        await asyncio.sleep(0.01)
        yield 2
        await asyncio.sleep(0.01)
        self.flag |= 1

    async def iter_trio(self):
        assert sniffio.current_async_library() == "trio"
        await trio.sleep(0.01)
        yield 1
        await trio.sleep(0.01)
        yield 2
        await trio.sleep(0.01)
        self.flag |= 1

    @asynccontextmanager
    async def ctx_asyncio(self):
        await asyncio.sleep(0.01)
        self.flag |= 1
        yield self
        await asyncio.sleep(0.01)
        self.flag |= 2

    @asynccontextmanager
    async def ctx_trio(self):
        await trio.sleep(0.01)
        self.flag |= 1
        yield self
        await trio.sleep(0.01)
        self.flag |= 2


class TestAdapt(aiotest.TestCase):
    @pytest.mark.trio
    async def test_asyncio_trio_adapted(self, loop):
        """Call asyncio from trio"""

        sth = SomeThing(loop)
        res = await aio_as_trio(sth.dly_trio_adapted, loop=loop)()
        assert res == 8
        assert sth.flag == 2

    @pytest.mark.trio
    async def test_asyncio_trio_adapted_no_call(self, loop):
        """Call asyncio from trio"""

        sth = SomeThing(loop)
        res = await aio_as_trio(sth.dly_trio_adapted)
        assert res == 8
        assert sth.flag == 2

    @pytest.mark.trio
    async def test_trio_asyncio_adapted(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio_adapted()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio(self, loop):
        sth = SomeThing(loop)
        res = await aio_as_trio(sth.dly_asyncio)()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_awaitable(self, loop):
        sth = SomeThing(loop)
        res = await aio_as_trio(sth.dly_asyncio())
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_future(self, loop):
        sth = SomeThing(loop)
        f = sth.dly_asyncio(do_test=False)
        f = asyncio.ensure_future(f)
        res = await aio_as_trio(f)
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_iter(self, loop):
        sth = SomeThing(loop)
        n = 0
        assert sniffio.current_async_library() == "trio"
        async for x in aio_as_trio(sth.iter_asyncio()):
            n += 1
            assert x == n
        assert n == 2
        assert sth.flag == 1

    async def run_asyncio_trio_iter(self, loop):
        sth = SomeThing(loop)
        n = 0
        assert sniffio.current_async_library() == "asyncio"
        async for x in trio_as_aio(sth.iter_trio()):
            n += 1
            assert x == n
        assert n == 2
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_asyncio_trio_iter(self, loop):
        await aio_as_trio(self.run_asyncio_trio_iter)(loop)

    @pytest.mark.trio
    async def test_trio_asyncio_ctx(self, loop):
        sth = SomeThing(loop)
        async with aio_as_trio(sth.ctx_asyncio()):
            assert sth.flag == 1
        assert sth.flag == 3

    async def run_asyncio_trio_ctx(self, loop):
        sth = SomeThing(loop)
        async with trio_as_aio(sth.ctx_trio()):
            assert sth.flag == 1
        assert sth.flag == 3

    @pytest.mark.trio
    async def test_asyncio_trio_ctx(self, loop):
        await aio_as_trio(self.run_asyncio_trio_ctx)(loop)


class TestAllow(aiotest.TestCase):
    async def run_asyncio_trio(self, loop):
        """Call asyncio from trio"""
        sth = SomeThing(loop)
        res = await trio_as_aio(sth.dly_trio, loop=loop)()
        assert res == 8
        assert sth.flag == 2

    @pytest.mark.trio
    async def test_asyncio_trio(self, loop):
        await allow_asyncio(self.run_asyncio_trio, loop)

    async def run_trio_asyncio(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio(do_test=False)
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio(self, loop):
        await allow_asyncio(self.run_trio_asyncio, loop)

    async def run_trio_asyncio_future(self, loop):
        sth = SomeThing(loop)
        f = sth.dly_asyncio(do_test=False)
        f = asyncio.ensure_future(f)
        res = await f
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_future(self, loop):
        await allow_asyncio(self.run_trio_asyncio_future, loop)

    def get_asyncio_future(self, loop, sth):
        async def set_result(future, sth):
            await asyncio.sleep(0.01)
            sth.flag |= 1
            future.set_result(4)

        f = loop.create_future()
        loop.create_task(set_result(f, sth))
        return f

    @pytest.mark.trio
    async def test_trio_asyncio_future_getter(self, loop):
        sth = SomeThing(loop)
        res = await allow_asyncio(self.get_asyncio_future, loop, sth)
        assert res == 4
        assert sth.flag == 1

    async def run_trio_asyncio_adapted(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio_adapted()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_adapted(self, loop):
        await allow_asyncio(self.run_trio_asyncio_adapted, loop)

    async def run_trio_asyncio_iter(self, loop):
        sth = SomeThing(loop)
        n = 0
        async for x in sth.iter_asyncio(do_test=False):
            n += 1
            assert x == n
        assert n == 2
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_iter(self, loop):
        await allow_asyncio(self.run_trio_asyncio_iter, loop)

    async def run_trio_asyncio_ctx(self, loop):
        sth = SomeThing(loop)
        async with sth.ctx_asyncio():
            assert sth.flag == 1
        assert sth.flag == 3

    @pytest.mark.trio
    async def test_trio_asyncio_ctx(self, loop):
        await allow_asyncio(self.run_trio_asyncio_ctx, loop)
