from tests import aiotest
import pytest
import trio
import trio_asyncio
from .. import utils as test_utils


class TestThread(aiotest.TestCase):
    @pytest.mark.trio
    async def test_ident(self, loop, config):
        threading = config.threading
        try:
            get_ident = threading.get_ident  # Python 3
        except AttributeError:
            get_ident = threading._get_ident  # Python 2

        result = {'ident': None}

        def work():
            result['ident'] = get_ident()

        fut = loop.run_in_executor(None, work)
        await loop.run_aio_coroutine(fut)

        # ensure that work() was executed in a different thread
        work_ident = result['ident']
        assert work_ident is not None
        assert work_ident != get_ident()

    @pytest.mark.trio
    async def test_run_twice(self, loop):
        result = []

        def work():
            result.append("run")

        fut = loop.run_in_executor(None, work)
        await loop.run_aio_future(fut)
        assert result == ["run"]

        # ensure that run_in_executor() can be called twice
        fut = loop.run_in_executor(None, work)
        await loop.run_aio_future(fut)
        assert result == ["run", "run"]

    @pytest.mark.trio
    async def test_policy(self, loop, config):
        asyncio = config.asyncio
        result = {'loop': 'not set'}  # sentinel, different than None

        def work():
            try:
                result['loop'] = asyncio.get_event_loop()
            except Exception as exc:
                result['loop'] = exc

        # get_event_loop() must return None in a different thread
        fut = loop.run_in_executor(None, work)
        await loop.run_aio_future(fut)
        assert isinstance(result['loop'], (AssertionError, RuntimeError))

    @pytest.mark.trio
    async def test_run_in_thread(self, config):
        threading = config.threading

        class LoopThread(threading.Thread):
            def __init__(self, event):
                super(LoopThread, self).__init__()
                self.loop = None
                self.event = event

            async def _run(self):
                async with trio_asyncio.open_loop() as loop:
                    self.loop = loop
                    loop.set_debug(True)

                    self.event.set()
                    await loop.wait_stopped()

            def run(self):
                trio.run(self._run)

        result = []

        # start an event loop in a thread
        event = threading.Event()
        thread = LoopThread(event)
        thread.start()
        event.wait()
        loop = thread.loop

        def func(loop):
            result.append(threading.current_thread().ident)
            loop.stop()

        # call func() in a different thread using the event loop
        tid = thread.ident
        loop.call_soon_threadsafe(func, loop)

        # wait for the other thread's event loop to terminate
        thread.join()
        assert result == [tid]
