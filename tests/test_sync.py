import pytest
import asyncio


class TestSync:
    def test_basic_mainloop(self, sync_loop):
        async def foo():
            return "bar"

        async def bar():
            return "baz"

        res = sync_loop.run_until_complete(foo())
        assert res == "bar"
        res = sync_loop.run_until_complete(bar())
        assert res == "baz"

    def test_explicit_mainloop(self):
        async def foo():
            return "bar"

        async def bar():
            return "baz"

        print("_A")
        loop = asyncio.new_event_loop()
        print("_B")
        res = loop.run_until_complete(foo())
        assert res == "bar"
        print("_C")
        res = loop.run_until_complete(bar())
        assert res == "baz"
        print("_close")
        loop.close()
        print("_closed")

    def test_basic_errloop(self, sync_loop):
        async def foo():
            raise RuntimeError("bar")

        with pytest.raises(RuntimeError) as res:
            sync_loop.run_until_complete(foo())
        if res.value.args[0] != "bar":
            raise res.value

    def test_explicit_errloop(self):
        async def foo():
            raise RuntimeError("bar")

        loop = asyncio.new_event_loop()
        with loop:
            with pytest.raises(RuntimeError) as res:
                try:
                    loop.run_until_complete(foo())
                finally:
                    pass
            if res.value.args[0] != "bar":
                raise res.value
