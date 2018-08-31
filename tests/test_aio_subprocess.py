"""Tests for events.py."""
import pytest

import collections.abc
import functools
import os
import signal
import subprocess
import sys
import errno
import unittest

import asyncio
from trio_asyncio import aio_as_trio

from . import utils as test_utils


class MySubprocessProtocol(asyncio.SubprocessProtocol):
    def __init__(self, loop):
        self.state = 'INITIAL'
        self.transport = None
        self.connected = asyncio.Future(loop=loop)
        self.completed = asyncio.Future(loop=loop)
        self.disconnects = {fd: asyncio.Future(loop=loop) for fd in range(3)}
        self.data = {1: b'', 2: b''}
        self.returncode = None
        self.got_data = {1: asyncio.Event(loop=loop), 2: asyncio.Event(loop=loop)}

    def connection_made(self, transport):
        self.transport = transport
        assert self.state == 'INITIAL', self.state
        self.state = 'CONNECTED'
        self.connected.set_result(None)

    def connection_lost(self, exc):
        assert self.state == 'CONNECTED', self.state
        self.state = 'CLOSED'
        self.completed.set_result(None)

    def pipe_data_received(self, fd, data):
        assert self.state == 'CONNECTED', self.state
        self.data[fd] += data
        self.got_data[fd].set()

    def pipe_connection_lost(self, fd, exc):
        assert self.state == 'CONNECTED', self.state
        if exc:
            self.disconnects[fd].set_exception(exc)
        else:
            self.disconnects[fd].set_result(exc)

    def process_exited(self):
        assert self.state == 'CONNECTED', self.state
        self.returncode = self.transport.get_returncode()


def check_terminated(returncode):
    if sys.platform == 'win32':
        assert isinstance(returncode, int)
        # expect 1 but sometimes get 0
    else:
        assert -signal.SIGTERM == returncode


def check_killed(returncode):
    if sys.platform == 'win32':
        assert isinstance(returncode, int)
        # expect 1 but sometimes get 0
    else:
        assert -signal.SIGKILL == returncode


@pytest.mark.trio
async def test_subprocess_exec(loop):
    await run_subprocess_exec(loop)


@aio_as_trio
async def run_subprocess_exec(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop), sys.executable, prog
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected
    assert 'CONNECTED' == proto.state

    stdin = transp.get_pipe_transport(0)
    stdin.write(b'Python The Winner')
    await proto.got_data[1].wait()
    with test_utils.disable_logger():
        transp.close()
    await proto.completed
    check_killed(proto.returncode)
    assert b'Python The Winner' == proto.data[1]


@pytest.mark.trio
async def test_subprocess_interactive(loop):
    await run_subprocess_interactive(loop)


@aio_as_trio
async def run_subprocess_interactive(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop), sys.executable, prog
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected
    assert 'CONNECTED' == proto.state

    stdin = transp.get_pipe_transport(0)
    stdin.write(b'Python ')
    await proto.got_data[1].wait()
    proto.got_data[1].clear()
    assert b'Python ' == proto.data[1]

    stdin.write(b'The Winner')
    await proto.got_data[1].wait()
    assert b'Python The Winner' == proto.data[1]

    with test_utils.disable_logger():
        transp.close()
    await proto.completed
    check_killed(proto.returncode)


@pytest.mark.trio
async def test_subprocess_shell(loop):
    await run_subprocess_shell(loop)


@aio_as_trio
async def run_subprocess_shell(loop):
    connect = loop.subprocess_shell(functools.partial(MySubprocessProtocol, loop), 'echo Python')
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected

    transp.get_pipe_transport(0).close()
    await proto.completed
    assert 0 == proto.returncode
    assert all(f.done() for f in proto.disconnects.values())
    assert proto.data[1].rstrip(b'\r\n') == b'Python'
    assert proto.data[2] == b''
    transp.close()


@pytest.mark.trio
async def test_subprocess_exitcode(loop):
    await run_subprocess_exitcode(loop)


@aio_as_trio
async def run_subprocess_exitcode(loop):
    connect = loop.subprocess_shell(
        functools.partial(MySubprocessProtocol, loop),
        'exit 7',
        stdin=None,
        stdout=None,
        stderr=None
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.completed
    assert 7 == proto.returncode
    transp.close()


@pytest.mark.trio
async def test_subprocess_close_after_finish(loop):
    await run_subprocess_close_after_finish(loop)


@aio_as_trio
async def run_subprocess_close_after_finish(loop):
    connect = loop.subprocess_shell(
        functools.partial(MySubprocessProtocol, loop),
        'exit 7',
        stdin=None,
        stdout=None,
        stderr=None
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    assert transp.get_pipe_transport(0) is None
    assert transp.get_pipe_transport(1) is None
    assert transp.get_pipe_transport(2) is None
    await proto.completed
    assert 7 == proto.returncode
    assert transp.close() is None


@pytest.mark.trio
async def test_subprocess_kill(loop):
    await run_subprocess_kill(loop)


@aio_as_trio
async def run_subprocess_kill(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop), sys.executable, prog
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected

    transp.kill()
    await proto.completed
    check_killed(proto.returncode)
    transp.close()


@pytest.mark.trio
async def test_subprocess_terminate(loop):
    await run_subprocess_terminate(loop)


@aio_as_trio
async def run_subprocess_terminate(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop), sys.executable, prog
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected

    transp.terminate()
    await proto.completed
    check_terminated(proto.returncode)
    transp.close()


@unittest.skipIf(sys.platform == 'win32', "Don't have SIGHUP")
@pytest.mark.trio
async def test_subprocess_send_signal(loop):
    await run_subprocess_send_signal(loop)


@aio_as_trio
async def run_subprocess_send_signal(loop):
    # bpo-31034: Make sure that we get the default signal handler (killing
    # the process). The parent process may have decided to ignore SIGHUP,
    # and signal handlers are inherited.
    old_handler = signal.signal(signal.SIGHUP, signal.SIG_DFL)
    try:
        prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo.py')

        connect = loop.subprocess_exec(
            functools.partial(MySubprocessProtocol, loop), sys.executable, prog
        )
        transp, proto = await connect
        assert isinstance(proto, MySubprocessProtocol)
        await proto.connected

        transp.send_signal(signal.SIGHUP)
        await proto.completed
        assert -signal.SIGHUP == proto.returncode
        transp.close()
    finally:
        signal.signal(signal.SIGHUP, old_handler)


@pytest.mark.trio
async def test_subprocess_stderr(loop):
    await run_subprocess_stderr(loop)


@aio_as_trio
async def run_subprocess_stderr(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo2.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop), sys.executable, prog
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected

    stdin = transp.get_pipe_transport(0)
    stdin.write(b'test')

    await proto.completed

    transp.close()
    assert b'OUT:test' == proto.data[1]
    assert proto.data[2].startswith(b'ERR:test'), proto.data[2]
    assert 0 == proto.returncode


@pytest.mark.trio
async def test_subprocess_stderr_redirect_to_stdout(loop):
    await run_subprocess_stderr_redirect_to_stdout(loop)


@aio_as_trio
async def run_subprocess_stderr_redirect_to_stdout(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo2.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop),
        sys.executable,
        prog,
        stderr=subprocess.STDOUT
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected

    stdin = transp.get_pipe_transport(0)
    assert transp.get_pipe_transport(1) is not None
    assert transp.get_pipe_transport(2) is None

    stdin.write(b'test')
    await proto.completed
    assert proto.data[1].startswith(b'OUT:testERR:test'), proto.data[1]
    assert b'' == proto.data[2]

    transp.close()
    assert 0 == proto.returncode


@pytest.mark.trio
async def test_subprocess_close_client_stream(loop):
    await run_subprocess_close_client_stream(loop)


@aio_as_trio
async def run_subprocess_close_client_stream(loop):
    prog = os.path.join(os.path.dirname(__file__), 'scripts', 'echo3.py')

    connect = loop.subprocess_exec(
        functools.partial(MySubprocessProtocol, loop), sys.executable, prog
    )
    transp, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.connected

    stdin = transp.get_pipe_transport(0)
    stdout = transp.get_pipe_transport(1)
    stdin.write(b'test')
    await proto.got_data[1].wait()
    assert b'OUT:test' == proto.data[1]

    stdout.close()
    await proto.disconnects[1]
    stdin.write(b'xxx')
    await proto.got_data[2].wait()
    if sys.platform != 'win32':
        assert b'ERR:BrokenPipeError' == proto.data[2]
    else:
        # After closing the read-end of a pipe, writing to the
        # write-end using os.write() fails with errno==EINVAL and
        # GetLastError()==ERROR_INVALID_NAME on Windows!?!  (Using
        # WriteFile() we get ERROR_BROKEN_PIPE as expected.)
        assert b'ERR:OSError' == proto.data[2]
    with test_utils.disable_logger():
        transp.close()
    await proto.completed
    check_killed(proto.returncode)


@pytest.mark.trio
async def test_subprocess_wait_no_same_group(loop):
    await run_subprocess_wait_no_same_group(loop)


@aio_as_trio
async def run_subprocess_wait_no_same_group(loop):
    # start the new process in a new session
    connect = loop.subprocess_shell(
        functools.partial(MySubprocessProtocol, loop),
        'exit 7',
        stdin=None,
        stdout=None,
        stderr=None,
        start_new_session=True
    )
    _, proto = await connect
    assert isinstance(proto, MySubprocessProtocol)
    await proto.completed
    assert 7 == proto.returncode


@pytest.mark.trio
async def test_subprocess_exec_invalid_args(loop):
    @aio_as_trio
    async def connect(**kwds):
        await loop.subprocess_exec(asyncio.SubprocessProtocol, 'pwd', **kwds)

    with pytest.raises(ValueError):
        await connect(universal_newlines=True)
    with pytest.raises(ValueError):
        await connect(bufsize=4096)
    with pytest.raises(ValueError):
        await connect(shell=True)


@pytest.mark.trio
async def test_subprocess_shell_invalid_args(loop):
    @aio_as_trio
    async def connect(cmd=None, **kwds):
        if not cmd:
            cmd = 'pwd'
        await loop.subprocess_shell(asyncio.SubprocessProtocol, cmd, **kwds)

    with pytest.raises(ValueError):
        await connect(['ls', '-l'])
    with pytest.raises(ValueError):
        await connect(universal_newlines=True)
    with pytest.raises(ValueError):
        await connect(bufsize=4096)
    with pytest.raises(ValueError):
        await connect(shell=False)
