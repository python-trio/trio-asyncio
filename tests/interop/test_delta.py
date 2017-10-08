import unittest
import pytest
import trio.asyncio
import asyncio
from trio.tests.asyncio import aiotest

DT = trio.asyncio.DeltaTime

class TestDeltaTime(aiotest.TestCase):
    def test_do(self):
        a = DT(10)
        assert a.delta == 10
        b = a + 5
        assert b.delta == 15
        a += 2
        assert a.delta == 12

        a -= 3
        assert a.delta == 9
        b = DT(3)
        assert a-b == 6
        assert (b-1).delta == 2
