# coding: utf-8

import trio
import queue
import asyncio
import threading
import outcome

from ._base import BaseTrioEventLoop


async def _sync(proc, *args):
    return proc(*args)


class SyncTrioEventLoop(BaseTrioEventLoop):
    """
    This is the "compatibility mode" implementation of the Trio/asyncio
    event loop. It runs synchronously, by delegating the Trio event loop to
    a separate thread.

    For best results, you should use the asynchronous
    :class:`trio_asyncio.TrioEventLoop` – if possible.
    """

    _thread = None
    _thread_running = False
    _stop_pending = False

    def __init__(self, **kw):
        super().__init__(**kw)

        # for sync operation
        self.__blocking_job_queue = queue.Queue()
        self.__blocking_result_queue = queue.Queue()

        # Synchronization
        self._some_deferred = 0

        self._start_loop()

    def stop(self):
        """Halt the main loop.

        Any callbacks queued before this point are processed before
        stopping.

        """

        def do_stop():
            self._stop_pending = False
            raise StopAsyncIteration


#        async def stop_me():
#            def kick_():
#                raise StopAsyncIteration
#            self._queue_handle(asyncio.Handle(kick_, (), self))
#            await self._main_loop()
#        if threading.current_thread() != self._thread:
#            self.__run_in_thread(stop_me)
#        else:

        if self._thread_running and not self._stop_pending:
            self._stop_pending = True
            self._queue_handle(asyncio.Handle(do_stop, (), self))

    def _queue_handle(self, handle):
        self._check_closed()

        def put(self, handle):
            self._some_deferred -= 1
            self._q_send.send_nowait(handle)

        # If we don't have a token, the main loop is not yet running
        # thus we can't have a race condition.
        #
        # On the other hand, if a request has been submitted (but not yet
        # processed) through self._token, any other requestss also must be
        # sent that way, otherwise they'd overtake each other.
        if self._token is not None and (self._some_deferred or \
                                        threading.current_thread() != self._thread):
            self._some_deferred += 1
            self._token.run_sync_soon(put, self, handle)
        else:
            self._q_send.send_nowait(handle)
        return handle

    def run_forever(self):
        if self._thread == threading.current_thread():
            raise RuntimeError("You can't nest calls to run_until_complete()/run_forever().")
        self.__run_in_thread(self._main_loop)

    def is_running(self):
        if self._closed:
            return False
        return self._thread_running

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

        if self._thread == threading.current_thread():
            raise RuntimeError("You can't nest calls to run_until_complete()/run_forever().")
        return self.__run_in_thread(self._run_coroutine, future)

    async def _run_coroutine(self, future):
        """Helper for run_until_complete().

        We need to make sure that a RuntimeError is raised
        if the loop is stopped before the future completes.

        This code runs in the Trio thread.
        """
        result = None
        future = asyncio.ensure_future(future, loop=self)

        def is_done(_):
            nonlocal result

            result = outcome.capture(future.result)
            self.stop()

        future.add_done_callback(is_done)
        try:
            await self._main_loop()
            try:
                while result is None:
                    try:
                        await self._main_loop_one(no_wait=True)
                    except StopAsyncIteration:
                        pass
            except trio.WouldBlock:
                pass
        finally:
            future.remove_done_callback(is_done)

        if result is None:
            raise RuntimeError('Event loop stopped before Future completed.')
        return result.unwrap()

    def __run_in_thread(self, async_fn, *args):
        self._check_closed()
        if self._thread is None:
            raise RuntimeError("You need to wrap your main code in a 'with loop:' statement.")
        if not self._thread.is_alive():
            raise RuntimeError("The Trio thread is not running")
        self.__blocking_job_queue.put((async_fn, args))
        res = self.__blocking_result_queue.get()
        if res is None:
            raise RuntimeError("Loop has died / terminated")
        return res.unwrap()

    def _start_loop(self):
        self._check_closed()

        if self._thread is None:
            self._thread = threading.Thread(
                name="trio-asyncio-" + threading.current_thread().name,
                target=trio.run,
                daemon=True,
                args=(self.__trio_thread_main,)
            )
            self._thread.start()
            x = self.__blocking_result_queue.get()
            if x is not True:
                raise RuntimeError("Loop could not be started", x)

    async def __trio_thread_main(self):
        # The non-context-manager equivalent of open_loop()
        async with trio.open_nursery() as nursery:
            asyncio.set_event_loop(self)
            await self._main_loop_init(nursery)
            self.__blocking_result_queue.put(True)

            while not self._closed:
                # This *blocks*
                req = self.__blocking_job_queue.get()
                if req is None:
                    break
                async_fn, args = req

                self._thread_running = True
                result = await outcome.acapture(async_fn, *args)
                self._thread_running = False
                if type(result) == outcome.Error and type(result.error) == trio.Cancelled:
                    res = RuntimeError("Main loop cancelled")
                    res.__cause__ = result.error.__cause__
                    result = outcome.Error(res)
                self.__blocking_result_queue.put(result)
            with trio.CancelScope(shield=True):
                await self._main_loop_exit()
            self.__blocking_result_queue.put(None)
            nursery.cancel_scope.cancel()

    def __enter__(self):
        # I'd like to enforce this, but … no way
        # if self._thread is not None:
        #    raise RuntimeError("This loop is already running.")
        # self._start_loop()
        return self

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
