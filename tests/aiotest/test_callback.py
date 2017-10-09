from tests import aiotest
import signal

class CallbackTests(aiotest.TestCase):
    def test_call_soon(self):
        result = []

        def hello_world(loop):
            result.append('Hello World')
            loop.stop()

        self.loop.call_soon(hello_world, self.loop)
        self.loop.run_forever()
        self.assertEqual(result, ['Hello World'])

    def test_call_soon_control(self):
        result = []

        def func(result, loop):
            loop.call_soon(append_result, loop, result, "yes")
            result.append(str(result))

        def append_result(loop, result, value):
            result.append(value)
            loop.stop()

        self.loop.call_soon(func, result, self.loop)
        self.loop.run_forever()
        # http://bugs.python.org/issue22875: Ensure that call_soon() does not
        # call append_result() immediatly, but when control returns to the
        # event loop, when func() is done.
        self.assertEqual(result, ['[]', 'yes'])

    def test_soon_stop_soon(self):
        result = []

        def hello():
            result.append("Hello")

        def world():
            result.append("World")
            self.loop.stop()

        self.loop.call_soon(hello)
        self.loop.stop()
        self.loop.call_soon(world)

        if False: # self.config.stopping:
            self.loop.run_forever()
            self.assertEqual(result, ["Hello", "World"])
        else:
            self.loop.run_forever()
            # ensure that world() is not called, since stop() was scheduled
            # before call_soon(world)
            self.assertEqual(result, ["Hello"])

            self.loop.run_forever()
            self.assertEqual(result, ["Hello", "World"])

    def test_close(self):
        config = self.config
        if not config.call_soon_check_closed:
            # http://bugs.python.org/issue22922 not implemented
            self.skipTest("call_soon() doesn't raise if the event loop is closed")

        self.loop.close()

        @config.asyncio.coroutine
        def test():
            pass

        func = lambda: False
        coro = test()
        self.addCleanup(coro.close)

        # operation blocked when the loop is closed
        with self.assertRaises(RuntimeError):
            self.loop.run_forever()
        with self.assertRaises(RuntimeError):
            fut = config.asyncio.Future(loop=self.loop)
            self.loop.run_until_complete(fut)
        with self.assertRaises(RuntimeError):
            self.loop.call_soon(func)
        with self.assertRaises(RuntimeError):
            self.loop.call_soon_threadsafe(func)
        with self.assertRaises(RuntimeError):
            self.loop.call_later(1.0, func)
        with self.assertRaises(RuntimeError):
            self.loop.call_at(self.loop.time() + .0, func)
        with self.assertRaises(RuntimeError):
            self.loop.run_in_executor(None, func)
        with self.assertRaises(RuntimeError):
            self.loop.create_task(coro)
        with self.assertRaises(RuntimeError):
            self.loop.add_signal_handler(signal.SIGTERM, func)


if __name__ == '__main__':
    import unittest
    unittest.main()
