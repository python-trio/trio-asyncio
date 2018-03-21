import datetime
from tests import aiotest
import pytest
import trio


class TestTimer(aiotest.TestCase):
    @pytest.mark.trio
    async def test_display_date(self, loop):
        result = []
        delay = 0.1
        count = 3
        h = trio.Event()

        def display_date(end_time, loop):
            if not end_time:
                end_time.append(loop.time() + delay * count)
            result.append(datetime.datetime.now())
            if (loop.time() + delay * 1.5) < end_time[0]:
                loop.call_later(delay, display_date, end_time, loop)
            else:
                loop.stop(h)

        loop.call_soon(display_date, [], loop)
        await h.wait()

        assert len(result) == count, result

    @pytest.mark.trio
    async def test_later_stop_later(self, loop):
        result = []

        def hello():
            result.append("Hello")

        def world(loop):
            result.append("World")
            loop.stop()

        loop.call_later(0.001, hello)
        loop.call_later(0.050, world, loop)

        await trio.sleep(0.030)
        assert result == ["Hello"]

        await loop.wait_stopped()
        assert result == ["Hello", "World"]
