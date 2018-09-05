import asyncio


class TestSync:
    def test_explicit_mainloop(self):
        async def foo():
            return "bar"

        async def bar():
            return "baz"

        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(foo())
        assert res == "bar"
        res = loop.run_until_complete(bar())
        assert res == "baz"
        loop.close()
