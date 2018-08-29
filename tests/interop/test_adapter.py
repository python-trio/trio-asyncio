import pytest
from trio_asyncio import aio_as_trio, allow_asyncio
from trio_asyncio import aio2trio, trio2aio
import asyncio
import trio
import sniffio
from tests import aiotest
import sys
from async_generator import asynccontextmanager


class SomeThing:
    flag = 0

    def __init__(self, loop):
        self.loop = loop

    @aio2trio
    async def dly_trio(self):
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "trio"
        await trio.sleep(0.01)
        self.flag |= 2
        return 8

    @trio2aio
    async def dly_asyncio_depr(self):
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 1
        return 4

    @aio_as_trio
    async def dly_asyncio_adapted(self):
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 1
        return 4

    async def dly_asyncio(self):
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 1
        return 4

    async def iter_asyncio(self):
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01, loop=self.loop)
        yield 1
        await asyncio.sleep(0.01, loop=self.loop)
        yield 2
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 1

    @asynccontextmanager
    async def ctx_asyncio(self):
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 1
        yield self
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 2

class TestAdapt(aiotest.TestCase):
    @pytest.mark.trio
    async def test_asyncio_trio(self, loop):
        """Call asyncio from trio"""

        sth = SomeThing(loop)
        res = await loop.run_asyncio(sth.dly_trio)
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
        f = sth.dly_asyncio()
        f = asyncio.ensure_future(f)
        res = await aio_as_trio(f)
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_depr(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio_depr()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_iter(self, loop):
        sth = SomeThing(loop)
        n = 0
        async for x in aio_as_trio(sth.iter_asyncio()):
            n += 1
            assert x == n
        assert n == 2
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_ctx(self, loop):
        sth = SomeThing(loop)
        async with aio_as_trio(sth.ctx_asyncio()):
            assert sth.flag == 1
        assert sth.flag == 3

class TestAllow(aiotest.TestCase):
    async def run_asyncio_trio(self, loop):
        """Call asyncio from trio"""
        sth = SomeThing(loop)
        res = await sth.dly_trio()
        assert res == 8
        assert sth.flag == 2

    @pytest.mark.trio
    async def test_asyncio_trio(self, loop):
        await allow_asyncio(self.run_asyncio_trio, loop)

    async def run_trio_asyncio(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio(self, loop):
        await allow_asyncio(self.run_trio_asyncio, loop)

    async def run_trio_asyncio_future(self, loop):
        sth = SomeThing(loop)
        f = sth.dly_asyncio()
        f = asyncio.ensure_future(f)
        res = await f
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_future(self, loop):
        await allow_asyncio(self.run_trio_asyncio_future, loop)

    async def run_trio_asyncio_depr(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio_depr()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_depr(self, loop):
        await allow_asyncio(self.run_trio_asyncio_depr, loop)

    async def run_trio_asyncio_iter(self, loop):
        sth = SomeThing(loop)
        n = 0
        async for x in sth.iter_asyncio():
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

