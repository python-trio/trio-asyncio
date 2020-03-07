"""Utilities shared by tests."""

import sys
import pytest
import contextlib
import logging
from asyncio.log import logger

from trio_asyncio import TrioAsyncioDeprecationWarning

def deprecate(tc):
    return pytest.warns(TrioAsyncioDeprecationWarning)

def deprecate_stdlib(tc, vers=None):
    if vers is None or sys.version_info >= vers:
        return pytest.deprecated_call()

    class _deprecate:
        def __init__(self, tc):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *tb):
            pass

    return _deprecate(tc)


@contextlib.contextmanager
def disable_logger():
    """Context manager to disable asyncio logger.

    For example, it can be used to ignore warnings in debug mode.
    """
    old_level = logger.level
    try:
        logger.setLevel(logging.CRITICAL + 1)
        yield
    finally:
        logger.setLevel(old_level)
