import trio
import attr
import threading

from functools import partial

__all__ = ['AsyncWorker']

class AsyncJob:
    """Holds one job to run"""
    def __init__(self, worker, proc, *args, token=None, event=None):
        self.worker = worker
        self.proc = proc
        self.args = args

        self._token = token
        self._event = event

        self._result = None
        self._wait = trio.Event()

    def __repr__(self):
        try:
            return "%s(%s, %s)" % (self.__class__.__name__,repr(self.proc), repr(self.args))
        except Exception:
            return "<%s ?>" % (self.__class__.__name__,)

    async def _run_bg(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        self._result = await trio.hazmat.Result.acapture(self.proc, *self.args)
        self.worker._done(self)

    async def _run(self, nursery):
        print("AT",self)
        await nursery.start(self._run_bg)   

    def _error(self, exc):
        self._result = trio.hazmat.Error(exc)
        self.worker._done(self)

    def _done(self):
        if self._token is not None:
            self._token.run_sync_soon(self._wait.set)
        if self._event is not None:
            self._event.set()

    async def result(self):
        await self._wait.wait()
        return self._result.unwrap()
        
class FastAsyncJob(AsyncJob):
    """No need to defer to a separate task. We hope."""
    async def _run(self, nursery):
        print("FT",self)
        self._result = await trio.hazmat.Result.acapture(self.proc, *self.args)
        self.worker._done(self)

class SyncJob(AsyncJob):
    """No need to defer to a separate task"""
    async def _run(self, nursery):
        print("ST",self)
        self._result = trio.hazmat.Result.capture(self.proc, *self.args)
        self.worker._done(self)
    
@attr.s
class AsyncWorker:
    """A class encapsulating calling Trio from a different thread.
    
    Args:
        nursery:
            the nursery to start longer-running tasks in.
        sync:
            If true, the queue will block synchronously, i.e. when there is
            no job running the whole thread will stall.

            Call :meth:`sync_on` to actually enable this. (Otherwise starting the
            queueing system would deadlock.)
    """
    nursery = attr.ib()
    sync = attr.ib(default=False)
    token = attr.ib(default=None)

    queue = attr.ib(default=attr.Factory(partial(trio.Queue,100)), init=False)
    sem = attr.ib(default=attr.Factory(partial(threading.Semaphore,value=1)), init=False)
    
    async def _runner(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        while True:
            if self.sync:
                print("WORK SEM A",self.sem._value)
                self.sem.acquire()
                print("WORK GET")
            job = await self.queue.get()
            if job is None: # sync_on
                print("WORK SEM B",self.sem._value)
            elif job._result is None: # new job
                if self.sync:
                    print("WORK GOT",job)
                await self.run_job(job)
            else: # job is done
                if self.sync:
                    print("WORK SEM C",self.sem._value)
                    assert self.sem.acquire(blocking=False)
                    print("WORK DONE",self.sem._value)
                job._done()
    
    async def run_job(self,job):
        await job._run(self.nursery)

    async def __aenter__(self):
        if self.token is not None:
            raise RuntimeError("You can't re-enter an AsyncCall handler")
        self.token = trio.hazmat.current_trio_token()
        await self.nursery.start(self._runner)

        return self
    
    async def __aexit__(self, *tb):
        self.nursery.cancel_scope.cancel()
        
    def sync_on(self):
        assert self.sync
        self.queue.put_nowait(None)

    def sync_off(self):
        assert self.sync
        print("WORK SEM REL A",self.sem._value)
        self.sem.release()

    def _submit(self, job):
        print("WORK SEND",job)
        if self.sync:
            print("WORK SEM REL B",self.sem._value)
            self.sem.release()
        try:
            self.queue.put_nowait(job)
        except trio.WouldBlock as exc:
            if self.sync:
                print("WORK SEM D",self.sem._value)
                self.sem.acquire(blocking=False)
            job._error(exc) # decrements _running

    def _done(self,job):
        self.queue.put_nowait(job)

    _jobs = {
        True: SyncJob,
        False: FastAsyncJob,
        None: AsyncJob,
    }
    async def run(self, proc, *args, sync=None):
        """Execute a job.
        
        Must be called from a different thread.
        
        Args:
            proc:
                the code you want to call.
            args:
                positional arguments are forwarded.
            sync:
                True:
                    `proc` is a synchronous function. The worker obviously
                    will be blocked while it is running.
                False:
                    `proc` is an async function. However, it runs in the
                    worker's queue handler and thus will also block the
                    queue.
                None:
                    `proc` is an async function which the worker will
                    run as a separate task. This is the default.
        """
        
        if self.sync:
            print("WORK SEM REL C2",self.sem._value)
            self.sem.release()
            self.sem.release()
        job = self._jobs.get(sync,sync)(self, proc, *args, token=trio.hazmat.current_trio_token())
        self.token.run_sync_soon(self._submit, job)
        return await job.result()

    def run_soon(self, proc, *args, sync=None, timeout=None):
        """Submit a job.

        As :meth:`run but is called from sync context.
        This will not wait for a result.
        """
        if self.sync:
            print("WORK SEM REL D2",self.sem._value)
            self.sem.release()
            self.sem.release()
        event=None
        if timeout is not None:
            event = threading.Event()
        job = self._jobs.get(sync,sync)(self, proc, *args, event=event)
        self.token.run_sync_soon(self._submit, job)
        if timeout is not None:
            event.wait(timeout=timeout)
            return job._result.unwrap()

    

