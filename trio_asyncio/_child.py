import os
import sys
import threading
import weakref
import outcome

import trio

import logging
logger = logging.getLogger(__name__)

_mswindows = (sys.platform == "win32")
if _mswindows:
    import _winapi

# TODO: use whatever works for Windows and MacOS/BSD

_children = weakref.WeakValueDictionary()


class UnknownStatus(ChildProcessError):
    pass


def _compute_returncode(status):
    if os.WIFSIGNALED(status):
        # The child process died because of a signal.
        return -os.WTERMSIG(status)
    elif os.WIFEXITED(status):
        # The child process exited (e.g sys.exit()).
        return os.WEXITSTATUS(status)
    elif os.WIFSTOPPED(status):
        return -os.WSTOPSIG(status)
    else:
        # This shouldn't happen.
        raise UnknownStatus(status)


def NOT_FOUND():
    return outcome.Error(ChildProcessError())


class ProcessWaiter:
    """I implement waiting for a child process."""

    __token = None
    __event = None
    __pid = None
    __result = None
    __thread = None
    _handle = None

    def __new__(cls, pid=None, _handle=None):
        """Grab an existing object if there is one"""
        self = None
        if pid is not None:
            self = _children.get(pid, None)
        if self is None:
            self = object.__new__(cls)
        return self

    def __init__(self, pid=None, _handle=None):
        if self.__pid is None:
            self._set_pid(pid, _handle)

    def _set_pid(self, pid, _handle=None):
        if self.__pid is not None:
            raise RuntimeError("You can't change the pid")
        if not isinstance(pid, int):
            raise RuntimeError("a PID needs to be an integer")

        self.__pid = pid
        _children[pid] = self

        if _mswindows:
            if _handle is None:
                _handle = _winapi.OpenProcess(_winapi.PROCESS_ALL_ACCESS, True, pid)
            self.__handle = _handle
        elif _handle is not None:
            raise RuntimeError("Process handles are a Windows thing.")

    async def wait(self):
        """Wait for this child process to end."""
        if self.__result is None:
            if self.__pid is None:
                raise RuntimeError("I don't know what to wait for!")

            # Check once, before doing the heavy lifting
            self._wait_pid(blocking=False)
            if self.__result is None:
                if self.__thread is None:
                    await self._start_waiting()
                await self.__event.wait()
        return self.__result.unwrap()

    async def _start_waiting(self):
        """Start the background thread that waits for a specific child"""
        self.__event = trio.Event()
        self.__token = trio.lowlevel.current_trio_token()

        self.__thread = threading.Thread(
            target=self._wait_thread, name="waitpid_%d" % self.__pid, daemon=True
        )
        self.__thread.start()

    def _wait_thread(self):
        """The background thread that waits for a specific child"""
        self._wait_pid(blocking=True)
        self.__token.run_sync_soon(self.__event.set)

    if _mswindows:

        def _wait_pid(self, blocking):
            assert self.__handle is not None
            if blocking:
                timeout = _winapi.INFINITE
            else:
                timeout = 0
            result = _winapi.WaitForSingleObject(self.__handle, timeout)
            if result != _winapi.WAIT_TIMEOUT:
                self.__result = _winapi.GetExitCodeProcess(self._handle)

    else:

        def _wait_pid(self, blocking):
            """check up on a child process"""
            assert self.__pid > 0

            try:
                pid, status = os.waitpid(self.__pid, 0 if blocking else os.WNOHANG)
            except ChildProcessError:
                # The child process may already be reaped
                # (may happen if waitpid() is called elsewhere).
                self.__result = NOT_FOUND()
            else:
                if pid == 0:
                    # The child process is still alive.
                    return
                del _children[pid]
                self._handle_exitstatus(status)

        def _handle_exitstatus(self, sts):
            """This overrides an internal API of subprocess.Popen"""
            self.__result = outcome.capture(_compute_returncode, sts)

    @property
    def returncode(self):
        if self.__result is None:
            return None
        return self.__result.unwrap()


async def wait_for_child(pid):
    waiter = ProcessWaiter(pid)
    return await waiter.wait()
