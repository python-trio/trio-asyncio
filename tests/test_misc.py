import pytest
import trio_asyncio
import asyncio
import trio

# from tests import aiotest


class Seen:
    flag = 0


class TestMisc:
    @pytest.mark.trio
    async def test_close_no_stop(self):
        with pytest.raises(RuntimeError):
            async with trio_asyncio.open_loop() as loop:

                def close_no_stop():
                    loop.close()

                loop.call_soon(close_no_stop)

                await trio.sleep(0.1)
                await loop.wait_closed()

    @pytest.mark.trio
    async def test_err1(self, loop):
        async def raise_err():
            raise RuntimeError("Foo")

        with pytest.raises(RuntimeError) as err:
            await loop.run_asyncio(raise_err)
        assert err.value.args[0] == "Foo"

    @pytest.mark.trio
    async def test_err3(self, loop):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1
            raise RuntimeError("Hello")

        async def call_nested():
            with pytest.raises(RuntimeError) as err:
                await loop.run_trio(nest)
            assert err.value.args[0] == "Hello"

        await loop.run_asyncio(call_nested)
        assert owch

    @pytest.mark.trio
    async def test_run(self, loop):
        owch = 0

        async def nest():
            await trio.sleep(0.01)
            nonlocal owch
            owch = 1

        async def call_nested():
            await loop.run_trio(nest)

        await loop.run_asyncio(call_nested)
        assert owch

    async def _test_run(self):
        owch = 0

        async def nest():
            await trio.sleep(0.01)
            nonlocal owch
            owch = 1

        async def call_nested():
            await trio_asyncio.run_trio(nest)

        await trio_asyncio.run_asyncio(call_nested)
        assert owch

    def test_run2(self):
        trio_asyncio.run(self._test_run)

    @pytest.mark.trio
    async def test_run_task(self):
        owch = 0

        def nest(x):
            nonlocal owch
            owch += x

        with pytest.raises(RuntimeError):
            trio_asyncio.run_trio_task(nest, 100)

        with pytest.raises(RuntimeError):
            with trio_asyncio.open_loop():
                nest(1000)

        async with trio_asyncio.open_loop():
            trio_asyncio.run_trio_task(nest, 1)
        await trio.sleep(0.05)
        assert owch == 1

    @pytest.mark.trio
    async def test_err2(self, loop):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1
            raise RuntimeError("Hello")

        async def call_nested():
            await loop.run_asyncio(nest)

        async def call_more_nested():
            with pytest.raises(RuntimeError) as err:
                await loop.run_trio(call_nested)
            assert err.value.args[0] == "Hello"

        await loop.run_asyncio(call_more_nested)
        assert owch

    @pytest.mark.trio
    async def test_run3(self, loop):
        owch = 0

        async def nest():
            nonlocal owch
            owch = 1

        async def call_nested():
            await loop.run_asyncio(nest)

        async def call_more_nested():
            await loop.run_trio(call_nested)

        await loop.run_asyncio(call_more_nested)
        assert owch

    @pytest.mark.trio
    async def test_cancel_sleep(self, loop):
        owch = 0

        def do_not_run():
            nonlocal owch
            owch = 1
            raise Exception("should not run")

        async def cancel_sleep():
            h = loop.call_later(0.2, do_not_run)
            await asyncio.sleep(0.1, loop=loop)
            h.cancel()
            await asyncio.sleep(0.3, loop=loop)

        await loop.run_asyncio(cancel_sleep)
        assert owch == 0
