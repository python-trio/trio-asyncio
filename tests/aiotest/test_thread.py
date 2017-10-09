from tests import aiotest

class ThreadTests(aiotest.TestCase):
    @classmethod
    def setUpClass(cls):
        super(ThreadTests, cls).setUpClass()
        if not cls.config.support_threads:
            raise aiotest.unittest.SkipTest("threads are not supported")

    def test_ident(self):
        threading = self.config.threading
        try:
            get_ident = threading.get_ident   # Python 3
        except AttributeError:
            get_ident = threading._get_ident   # Python 2

        result = {'ident': None}

        def work():
            result['ident'] = get_ident()

        fut = self.loop.run_in_executor(None, work)
        self.loop.run_until_complete(fut)

        # ensure that work() was executed in a different thread
        work_ident = result['ident']
        self.assertIsNotNone(work_ident)
        self.assertNotEqual(work_ident, get_ident())

    def test_run_twice(self):
        result = []

        def work():
            result.append("run")

        fut = self.loop.run_in_executor(None, work)
        self.loop.run_until_complete(fut)
        self.assertEqual(result, ["run"])

        # ensure that run_in_executor() can be called twice
        fut = self.loop.run_in_executor(None, work)
        self.loop.run_until_complete(fut)
        self.assertEqual(result, ["run", "run"])

    def test_policy(self):
        asyncio = self.config.asyncio
        result = {'loop': 'not set'}   # sentinel, different than None

        def work():
            try:
                result['loop'] = asyncio.get_event_loop()
            except Exception as exc:
                result['loop'] = exc

        # get_event_loop() must return None in a different thread
        fut = self.loop.run_in_executor(None, work)
        self.loop.run_until_complete(fut)
        self.assertIsInstance(result['loop'], (AssertionError, RuntimeError))

    def test_run_in_thread(self):
        asyncio = self.config.asyncio
        threading = self.config.threading

        class LoopThread(threading.Thread):
            def __init__(self, event):
                super(LoopThread, self).__init__()
                self.loop = None
                self.event = event

            def run(self):
                self.loop = asyncio.new_event_loop()
                try:
                    self.loop.set_debug(True)
                    asyncio.set_event_loop(self.loop)

                    self.event.set()
                    self.loop.run_forever()
                finally:
                    self.loop.close()
                    asyncio.set_event_loop(None)

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

        # stop the event loop
        thread.join()
        self.assertEqual(result, [tid])


if __name__ == '__main__':
    import unittest
    unittest.main()
