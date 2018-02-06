import trio
import queue
import asyncio
import threading

from functools import partial

from .base import BaseTrioEventLoop
from .handles import Handle

async def _sync(proc, *args):
    return proc(*args)

class SyncTrioEventLoop(BaseTrioEventLoop):
    """
    This is the "compatibility mode" implementation of the Trio/asyncio
    event loop. It runs async code in a separate thread.

    For best results, you should switch to the asynchronous :class:`TrioEventLoop`.
    """

    _thread = None

    def __init__(self, **kw):
        super().__init__(**kw)

        # for sync operation
        self.__blocking_job_queue = queue.Queue()
        self.__blocking_result_queue = queue.Queue()

        # Synchronization
        self._some_deferred = 0
        #self._stop_count = 0

    def stop(self):
        """Halt the main loop.

        If this method is called from the main thread, it will wait until
        the loop is stopped.
        """
        #self._stop_count += 1
        def kick():
            raise StopIteration
        async def stop_me():
            h = trio.Event()
            def kick_():
                h.set()
                raise StopIteration
            self._queue_handle(Handle(kick_,(),self,True))
            await h.wait()
        if threading.current_thread() != self._thread:
            self.__run_in_thread(stop_me)
        else:
            self._queue_handle(Handle(kick,(),self,True))


    def _queue_handle(self, handle):
        self._check_closed()
        def put(self,handle):
            self._some_deferred -= 1
            self._q.put_nowait(handle)
            
        # If we don't have a token, the main loop is not yet running
        # thus we can't have a race condition.
        # 
        # On the other hand, if a request has been submitted (but not yet
        # processed) through self._token, any other requestss also must be
        # sent that way, otherwise they'd overtake each other.
        if self._token is not None and (self._some_deferred or threading.current_thread() != self._thread):
            self._some_deferred += 1
            self._token.run_sync_soon(put,self, handle)
        else:
            self._q.put_nowait(handle)
        return handle

    def run_forever(self):
        self.__start_loop()
        if self._thread == threading.current_thread():
            raise RuntimeError("You can't nest calls to run_until_complete()/run_forever().")
        try:
            #if self._stop_count == 0:
            self.__run_in_thread(self.wait_stopped)
        finally:
            pass
            #if self._stop_count > 0:
                #self._stop_count -= 1

    def is_running(self):
        if self._closed:
            return False
        return self._thread is not None

    def time(self):
        if self._task is None:
            self.__start_loop()
        return super().time()

    def _add_reader(self, fd, callback, *args):
        if self._thread is None or self._thread == threading.current_thread():
            super()._add_reader(fd, callback, *args)
        else:
            self.__run_in_thread(_sync, super()._add_reader, fd, callback, *args)

    def _add_writer(self, fd, callback, *args):
        if self._thread is None or self._thread == threading.current_thread():
            super()._add_writer(fd, callback, *args)
        else:
            self.__run_in_thread(_sync, super()._add_writer, fd, callback, *args)
        
    def run_until_complete(self, future):
        """Run until the Future is done.

        If the argument is a coroutine, it is wrapped in a Task.

        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.

        Return the Future's result, or raise its exception.
        """

        self.__start_loop()
        if self._thread == threading.current_thread():
            raise RuntimeError("You can't nest calls to run_until_complete()/run_forever().")
        try:
            return self.__run_in_thread(self._run_coroutine, future)
        finally:
            self.stop()

    async def _run_coroutine(self, future):
        """Helper for run_until_complete().

        We need to make sure that a RuntimeError is raised if the loop is stopped
        before the future completes.
        """
        done = trio.Event()
        result = None
        future = asyncio.ensure_future(future, loop=self)

        def is_done(_):
            nonlocal result

            result = trio.hazmat.Result.capture(future.result)
            done.set()
        future.add_done_callback(is_done)

        async def monitor_stop(task_status=trio.TASK_STATUS_IGNORED):
            nonlocal result

            task_status.started()
            await self.wait_stopped()
            result = trio.hazmat.Error(RuntimeError('Event loop stopped before Future completed.'))
            done.set()

        async with trio.open_nursery() as nursery:
            await nursery.start(monitor_stop)
            await done.wait()
            future.remove_done_callback(is_done)
            nursery.cancel_scope.cancel()
            return result.unwrap()

    def __run_in_thread(self, async_fn, *args, _start_loop=True):
        self._check_closed()
        if not self._thread.is_alive():
            raise RuntimeError("The Trio thread is not running")
        self.__blocking_job_queue.put((async_fn, args, _start_loop))
        res = self.__blocking_result_queue.get()
        return res.unwrap()

    def __start_loop(self):
        self._check_closed()

        if self._thread is None:
            self._thread = threading.Thread(
                name="trio-asyncio-"+threading.current_thread().name,
                target=trio.run,
                args=(self.__trio_thread_main,))
            self._thread.start()
            self.__run_in_thread(self._sync)

    async def __trio_thread_main(self):
        # The non-context-manager equivalent of open_loop()
        async with trio.open_nursery() as nursery:
            asyncio.set_event_loop(self)
            await self._main_loop_init(nursery)
            await nursery.start(self._main_loop)

            while not self._closed:
                # This *blocks*
                req = self.__blocking_job_queue.get()
                if req is None:
                    break
                async_fn, args, start_loop = req
                if start_loop and self._stopped.is_set():
                    await nursery.start(self._main_loop)
                    
                result = await trio.hazmat.Result.acapture(async_fn, *args)
                self.__blocking_result_queue.put(result)
            self.stop()
            await self.wait_stopped()
            await self._main_loop_exit()
            self.__blocking_result_queue.put(None)

    def add_signal_handler(self, sig, callback, *args):
        self.__start_loop()
        return super().add_signal_handler(sig, callback, *args)

    def __enter__(self):
        if self._thread is not None:
            raise RuntimeError("This loop is already running.")
        self.__start_loop()
        
    def __exit__(self, *tb):
        self.stop()
        self.close()
        assert self._thread is None

    def _close(self):
        """Hook to terminate the thread"""
        if self._thread is not None:
            if self._thread == threading.current_thread():
                raise RuntimeError("You can't close a sync loop from the inside")
            self.__blocking_job_queue.put(None)
            self._thread.join()
            self._thread = None
        super()._close()

