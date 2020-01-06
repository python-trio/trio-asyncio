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
        RuntimeWarning,
        "Can't run the Python asyncio tests because they're not installed. "
        "On a Debian/Ubuntu system, you might need to install the "
        "libpython{}.{}-testsuite package.".format(*sys.version_info[:2])
    )
else:
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
            return UnittestOnlyPackage(py.path.local(test_asyncio.__file__), parent)
