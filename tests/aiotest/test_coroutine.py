from trio.tests.asyncio import aiotest

async def hello_world(asyncio, result, delay):
    result.append("Hello")
    # retrieve the event loop from the policy
    await asyncio.sleep(delay)
    result.append('World')
    return "."

class CoroutineTests(aiotest.TestCase):
    def test_hello_world(self):
        result = []
        coro = hello_world(self.config.asyncio, result, 0.001)
        self.loop.run_until_complete(coro)
        self.assertEqual(result, ['Hello', 'World'])

    def test_waiter(self):
        async def waiter(asyncio, hello_world, result):
            loop = asyncio.get_event_loop()
            fut = asyncio.Future(loop=loop)
            loop.call_soon(fut.set_result, "Future")

            value = await fut
            result.append(value)

            value = await hello_world(asyncio, result, 0.001)
            result.append(value)

        result = []
        coro = waiter(self.config.asyncio, hello_world, result)
        self.loop.run_until_complete(coro)
        self.assertEqual(result, ['Future', 'Hello', 'World', '.'])


if __name__ == '__main__':
    import unittest
    unittest.main()
