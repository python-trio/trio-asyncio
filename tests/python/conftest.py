import os
import sys
import warnings
import py
import pytest
import unittest

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
    asyncio_test_dir = py.path.local(test_asyncio.__path__[0])

    def aio_test_nodeid(fspath):
        relpath = fspath.relto(asyncio_test_dir)
        if relpath:
            return "/Python-{}.{}/test_asyncio/".format(*sys.version_info[:2]) + relpath
        return None


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
                yield node


    @pytest.hookimpl(tryfirst=True)
    def pytest_pycollect_makemodule(path, parent):
        # Convert collection of trio-asyncio tests.python into collection of
        # test.test_asyncio from the Python standard library.
        candidate = str(path.realpath())
        expected = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "__init__.py")
        )
        if candidate == expected:
            fspath = py.path.local(test_asyncio.__file__)
            return UnittestOnlyPackage(fspath, parent, nodeid=aio_test_nodeid(fspath))


    def pytest_collection_modifyitems(items):
        by_id = {item.nodeid: item for item in items}
        aio_test_root = aio_test_nodeid(asyncio_test_dir / "foo")[:-3]

        def mark(marker, rel_id):
            by_id[aio_test_root + rel_id].add_marker(marker)

        def xfail(rel_id):
            mark(pytest.mark.xfail, rel_id)

        def skip(rel_id):
            mark(pytest.mark.skip, rel_id)

        xfail(
            "test_base_events.py::BaseEventLoopWithSelectorTests::"
            "test_log_slow_callbacks"
        )

        # This hangs, probably due to the thread shenanigans (it works
        # fine with a greenlet-based sync loop)
        skip("test_base_events.py::RunningLoopTests::test_running_loop_within_a_loop")

        # trio-asyncio doesn't use a task factory
        xfail(
            "test_tasks.py::RunCoroutineThreadsafeTests::"
            "test_run_coroutine_threadsafe_task_factory_exception"
        )
