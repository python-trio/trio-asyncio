import sys
import os.path
from pathlib import Path
import warnings
import pytest
import asyncio
import trio_asyncio
import inspect
import unittest


@pytest.fixture
async def loop():
    async with trio_asyncio.open_loop() as loop:
        try:
            yield loop
        finally:
            await loop.stop().wait()


# auto-trio-ize all async functions
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = pytest.mark.trio(pyfuncitem.obj)


# Map collection of the python/ submodule to python's asyncio unittests
try:
    # the global 'test' package installed with Python
    from test import test_asyncio
except ImportError:
    warnings.warn(
        "Can't run the Python asyncio tests because they're not installed. "
        "On a Debian/Ubuntu system, you might need to install the "
        "libpython{}.{}-testsuite package.".format(*sys.version_info[:2]),
        RuntimeWarning,
    )
else:
    # threading_cleanup() causes a 5-second or so delay (100
    # gc.collect()'s) and warning on any test that holds a reference
    # to the event loop in the testsuite class, because
    # SyncTrioEventLoop spawns a thread that only exits when the
    # loop is closed. Nerf it.
    try:
        from test.support import threading_cleanup
    except ImportError:
        # Python 3.10+
        from test.support.threading_helper import threading_cleanup

    def threading_no_cleanup(*original_values):
        pass

    threading_cleanup.__code__ = threading_no_cleanup.__code__

    asyncio_test_dir = Path(test_asyncio.__path__[0])

    def aio_test_nodeid(path):
        try:
            relpath = path.relative_to(asyncio_test_dir)
        except ValueError:
            return None
        else:
            return "/Python-{}.{}/test_asyncio/{}".format(
                *sys.version_info[:2], relpath
            )

    # A pytest.Module that will only collect unittest.TestCase
    # classes, so that we don't get spurious warnings about things
    # like TestSelector and TestEventLoop (which are fakes used by the
    # tests, directly containing no tests themselves) not being collectable.
    class UnittestOnlyModule(pytest.Module):
        def istestclass(self, obj, name):
            return isinstance(obj, unittest.TestCase)

    # A pytest.Package whose only purpose is to mark that its children should
    # become UnittestOnlyModules (or other UnittestOnlyPackages).
    class UnittestOnlyPackage(pytest.Package):
        def collect(self):
            for node in super().collect():
                if isinstance(node, pytest.Package):
                    node.__class__ = UnittestOnlyPackage
                elif isinstance(node, pytest.Module):
                    node.__class__ = UnittestOnlyModule
                node._nodeid = node._nodeid.replace("/__init__.py::", "/")
                node._nodeid = node._nodeid.replace("/.::", "/")
                yield node

    @pytest.hookimpl(tryfirst=True)
    def pytest_collect_directory(path, parent):
        from . import python

        candidate = str(path.resolve())
        expected = os.path.realpath(os.path.dirname(python.__file__))
        if candidate == expected:
            fwd_path = Path(os.path.dirname(test_asyncio.__file__))
            node = UnittestOnlyPackage.from_parent(parent, path=fwd_path)
            # This keeps all test names from showing as "."
            node._nodeid = aio_test_nodeid(fwd_path)
            return node

    def pytest_collection_modifyitems(items):
        by_id = {item.nodeid: item for item in items}
        aio_test_root = aio_test_nodeid(asyncio_test_dir / "foo")[:-3]

        def mark(marker, rel_id):
            try:
                by_id[aio_test_root + rel_id].add_marker(marker)
            except KeyError:
                warnings.warn(
                    "Tried to add marker {} to {}, but that test doesn't exist.".format(
                        marker, rel_id
                    ),
                    RuntimeWarning,
                    stacklevel=3,
                )

        def xfail(rel_id):
            mark(pytest.mark.xfail, rel_id)

        def skip(rel_id):
            mark(pytest.mark.skip, rel_id)

        # This hangs, probably due to the thread shenanigans (it works
        # fine with a greenlet-based sync loop)
        skip("test_base_events.py::RunningLoopTests::test_running_loop_within_a_loop")

        # Remainder of these have unclear issues
        if sys.version_info < (3, 8):
            xfail(
                "test_base_events.py::BaseEventLoopWithSelectorTests::"
                "test_log_slow_callbacks"
            )
        if sys.version_info >= (3, 8):
            xfail(
                "test_tasks.py::RunCoroutineThreadsafeTests::"
                "test_run_coroutine_threadsafe_task_cancelled"
            )
            if sys.version_info < (3, 11):
                xfail(
                    "test_tasks.py::RunCoroutineThreadsafeTests::"
                    "test_run_coroutine_threadsafe_with_timeout"
                )
            if sys.platform == "win32":
                # hangs on 3.11+, fails without hanging on 3.8-3.10
                skip("test_windows_events.py::ProactorLoopCtrlC::test_ctrl_c")

        if sys.implementation.name == "pypy":
            # This test depends on the C implementation of asyncio.Future, and
            # unlike most such tests it is not configured to be skipped if
            # the C implementation is not available
            xfail(
                "test_futures.py::CFutureInheritanceTests::"
                "test_inherit_without_calling_super_init"
            )
            if sys.version_info < (3, 8):
                # These tests assume CPython-style immediate finalization of
                # objects when they become unreferenced
                for test in (
                    "test_create_connection_memory_leak",
                    "test_handshake_timeout",
                    "test_start_tls_client_reg_proto_1",
                ):
                    xfail("test_sslproto.py::SelectorStartTLSTests::{}".format(test))

            # This test depends on the name of the loopback interface. On Github Actions
            # it fails on macOS always, and on Linux/Windows except on 3.8.
            skip(
                "test_base_events.py::BaseEventLoopWithSelectorTests::"
                "test_create_connection_ipv6_scope"
            )

            if sys.platform == "darwin":
                # https://foss.heptapod.net/pypy/pypy/-/issues/3964 causes infinite loops
                for nodeid, item in by_id.items():
                    if "sendfile" in nodeid:
                        item.add_marker(pytest.mark.skip)

        if sys.version_info >= (3, 11):
            # This tries to use a mock ChildWatcher that does something unlikely.
            # We don't support it because we don't actually use the ChildWatcher
            # to manage subprocesses.
            xfail(
                "test_subprocess.py::GenericWatcherTests::"
                "test_create_subprocess_fails_with_inactive_watcher"
            )

            # This forks a child process and tries to run a new event loop there,
            # but Trio isn't fork-safe -- it hangs nondeterministically.
            skip("test_events.py::TestPyGetEventLoop::test_get_event_loop_new_process")
            skip("test_events.py::TestCGetEventLoop::test_get_event_loop_new_process")

        if sys.version_info >= (3, 9):
            # This tries to create a new loop from within an existing one,
            # which we don't support.
            xfail("test_locks.py::ConditionTests::test_ambiguous_loops")

        if sys.version_info >= (3, 12):
            # This test sets signal handlers from within a coroutine,
            # which doesn't work for us because SyncTrioEventLoop runs on
            # a non-main thread.
            xfail("test_unix_events.py::TestFork::test_fork_signal_handling")

            # This test explicitly uses asyncio.tasks._c_current_task,
            # bypassing our monkeypatch.
            xfail(
                "test_tasks.py::CCurrentLoopTests::test_current_task_with_implicit_loop"
            )

            # These tests assume asyncio.sleep(0) is sufficient to run all pending tasks
            xfail(
                "test_futures2.py::PyFutureTests::test_task_exc_handler_correct_context"
            )
            xfail(
                "test_futures2.py::CFutureTests::test_task_exc_handler_correct_context"
            )

            # This test assumes that get_event_loop_policy().get_event_loop() doesn't
            # automatically return the running loop
            skip(
                "test_subprocess.py::GenericWatcherTests::test_create_subprocess_with_pidfd"
            )
