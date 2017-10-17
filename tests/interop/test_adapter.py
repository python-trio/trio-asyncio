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


class AdaptTests(aiotest.TestCase):
    def test_asyncio_trio(self):
        """Call asyncio from trio"""

        sth = SomeThing(self.loop)
        res = self.loop.run_until_complete(sth.dly_trio())
        assert res == 8
        assert sth.flag == 2

    def test_trio_asyncio(self):
        sth = SomeThing(self.loop)
        res = self.loop.run_task(sth.dly_asyncio)
        assert res == 4
        assert sth.flag == 1

