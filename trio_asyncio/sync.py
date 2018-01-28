import queue
import trio
from trio_asyncio import TrioEventLoop
import threading
from functools import partial

class SyncTrioEventLoop(TrioEventLoop):
	__in_closing = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__blocking_job_queue = queue.Queue()
        self.__blocking_result_queue = queue.Queue()

    async def __trio_thread_main(self):
		# The non-context-manager equivalent of open_loop()
        async with trio.open_nursery() as nursery:
			asyncio.set_event_loop(self)
			await self._main_loop_init(nursery)
			await nursery.start(self._main_loop())

            while not self._closed:
                # This *blocks*
                async_fn = self.__blocking_job_queue.get()
				if async_fn is None:
					break
                result = await trio.hazmat.Result.acapture(async_fn)
                self.__blocking_result_queue.put(result)
			await self.stop().wait()
			await self._main_loop_exit()
			self.close()
			self.__blocking_result_queue.put(None)

    def __run_in_thread(self, async_fn, *args):
        if not self.__thread.is_alive():
            self.__thread.start()
        self.__blocking_job_queue.put(partial(async_fn, *args))
        return self.__blocking_result_queue.get().unwrap()

	def _queue_handle(self):
		if self._thread is None:
			raise RuntimeError("Loop is not running")

    def run_until_complete(self, fut):
        return self.__run_in_thread(self.run_future, fut)

    def run_forever(self):
        self.__run_in_thread(self.wait_stopped)

    def close(self):
        self.__blocking_job_queue.put(None)
        self._thread.join()
		super().close()

    def __enter__(self):
		assert self._thread is None
		assert self._closed

        self.__thread = threading.Thread(
            target=trio.run,
            args=(self.__trio_thread_main,))
        return self

    def __exit__(self, *tb):
        self.close()
		self._thread = None

