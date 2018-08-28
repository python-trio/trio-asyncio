import pytest
from trio_asyncio import aio_as_trio
from trio_asyncio import aio2trio, trio2aio
import asyncio
import trio
import sniffio
from tests import aiotest
import sys


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
    async def dly_asyncio(self):
        if sys.version_info >= (3, 7):
            assert sniffio.current_async_library() == "asyncio"
        await asyncio.sleep(0.01, loop=self.loop)
        self.flag |= 1
        return 4


class TestAdapt(aiotest.TestCase):
    @pytest.mark.trio
    async def test_asyncio_trio(self, loop):
        """Call asyncio from trio"""

        sth = SomeThing(loop)
        res = await loop.run_asyncio(sth.dly_trio)
        assert res == 8
        assert sth.flag == 2

    @pytest.mark.trio
    async def test_trio_asyncio(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio()
        assert res == 4
        assert sth.flag == 1

    @pytest.mark.trio
    async def test_trio_asyncio_depr(self, loop):
        sth = SomeThing(loop)
        res = await sth.dly_asyncio_depr()
        assert res == 4
        assert sth.flag == 1

