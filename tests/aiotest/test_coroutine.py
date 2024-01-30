from tests import aiotest
import trio_asyncio
import pytest


async def hello_world(asyncio, result, delay, loop):
    result.append("Hello")
    # retrieve the event loop from the policy
    await asyncio.sleep(delay)
    result.append("World")
    return "."


class TestCoroutine(aiotest.TestCase):
    @pytest.mark.trio
    async def test_hello_world(self, loop, config):
        result = []
        coro = hello_world(config.asyncio, result, 0.001, loop)
        await loop.run_aio_coroutine(config.asyncio.ensure_future(coro))
        assert result == ["Hello", "World"]

    @pytest.mark.trio
    async def test_waiter(self, loop, config):
        async def waiter(asyncio, hello_world, result):
            fut = asyncio.Future()
            loop.call_soon(fut.set_result, "Future")

            value = await fut
            result.append(value)

            value = await hello_world(asyncio, result, 0.001, loop)
            result.append(value)

        result = []
        await trio_asyncio.aio_as_trio(waiter)(config.asyncio, hello_world, result)
        assert result == ["Future", "Hello", "World", "."]
