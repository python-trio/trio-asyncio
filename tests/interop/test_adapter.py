import unittest
import pytest
from trio_asyncio import aio2trio, trio2aio
import asyncio
import trio
from tests import aiotest

class SomeThing:
    flag = 0
    def __init__(self,loop):
        self.loop = loop

    @aio2trio
    async def dly_trio(self):
        await trio.sleep(0.01)
        self.flag |= 2
        return 8

    @trio2aio
    async def dly_asyncio(self):
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

