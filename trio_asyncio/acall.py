import trio
import attr

from functools import partial

__all__ = ['AsyncWorker']

class AsyncJob:
    """Holds one job to run"""
    def __init__(self, proc, *args):
        self.proc = proc
        self.args = args
        self._token = trio.hazmat.current_trio_token()
        self._result = None
        self._wait = trio.Event()

    async def _run_bg(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        self._result = await trio.hazmat.Result.acapture(self.proc, *self.args)
        self._token.run_sync_soon(self._wait.set)

    async def _run(self, nursery):
        await nursery.start(self._run_bg)   

    def _error(self, exc):
        self._result = trio.hazmat.Error(exc)
        self._token.run_sync_soon(self._wait.set)

    async def result(self):
        await self._wait.wait()
        return self._result.unwrap()
        
class FastAyncJob(AsyncJob):
    """No need to defer to a separate task. We hope."""
    async def _run(self, nursery):
        self._result = trio.hazmat.Result.capture(self.proc, *self.args)
        self._token.run_sync_soon(self._wait.set)

class SyncJob(AsyncJob):
    """No need to defer to a separate task"""
    async def _run(self, nursery):
        self._result = trio.hazmat.Result.capture(self.proc, *self.args)
        self._token.run_sync_soon(self._wait.set)
    
@attr.s
class AsyncWorker:
    """A class encapsulating calling Trio from a different thread."""
    nursery = attr.ib()
    token = attr.ib(default=None)
    queue = attr.ib(default=attr.Factory(partial(trio.Queue,100)))
    
    async def _runner(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for job in self.queue:
            await self.run_job(job)
    
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
        
    def _submit(self, job):
        try:
            self.queue.put_nowait(job)
        except trio.WouldBlock as exc:
            job._error(exc)

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
        job = (AsyncJob if sync is None else SyncJob if sync else AsyncJob)(proc, *args)
        self.token.run_sync_soon(self._submit, job)
        return await job.result()

    def run_soon(proc, *args, sync=None):
        """Submit a job.

        As :meth:`run but is called from sync context.
        This will not wait for a result.
        """
    

