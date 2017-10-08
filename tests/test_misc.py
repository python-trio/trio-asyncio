import unittest
import pytest
import trio.asyncio
import asyncio
import os
from trio.tests.asyncio import aiotest


class Seen:
    flag = 0


class MiscTests(aiotest.TestCase):
    def test_close_no_stop(self):
        def close_no_stop():
            self.loop.close()
        self.loop.call_soon(close_no_stop)

        with pytest.raises(RuntimeError) as err:
            res = self.loop.run_forever()
        assert "before closing" in err.value.args[0]

    def test_err(self):
        async def err():
            raise RuntimeError("Foo")

        with pytest.raises(RuntimeError) as err:
            res = self.loop.run_task(err)
        assert err.value.args[0] == "Foo"

    def test_err(self):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1
            raise Exception("should not run")

        async def call_nested():
            with pytest.raises(RuntimeError) as err:
                self.loop.run_task(next)
            assert "already running" in err.value.args[0]

        self.loop.run_task(call_nested)
        assert not owch

    def test_cancel_sleep(self):
        owch = 0

        def do_not_run():
            nonlocal owch
            owch = 1
            raise Exception("should not run")

        async def cancel_sleep():
            h = self.loop.call_later(0.1, do_not_run)
            await trio.sleep(0.05)
            h.cancel()
            await trio.sleep(0.2)

        self.loop.run_task(cancel_sleep)
        assert owch == 0

    def test_restore_fds(self):
        data = b""
        r,w = os.pipe()

        def has_data():
            nonlocal data
            data += os.read(r,99)
        def send_data(x):
            os.write(w,b'hip')
            self.loop.call_soon(self.loop.remove_writer,w)

        async def x1():
            self.loop.add_reader(r,has_data)
        async def x2():
            self.loop.add_writer(w,send_data)
        async def x3():
            await asyncio.sleep(0.2, loop=self.loop)
            assert not self.loop.remove_writer(r)
            assert self.loop.remove_reader(r)
        async def x4():
            assert not self.loop.remove_reader(r)

        self.loop.run_until_complete(x1())
        self.loop.run_until_complete(x2())
        self.loop.run_until_complete(x3())
        self.loop.run_until_complete(x4())

