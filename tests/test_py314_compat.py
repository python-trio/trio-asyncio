"""Import / policy compatibility across asyncio API changes (esp. Python 3.14)."""

import asyncio
import sys

import pytest

import trio_asyncio
from trio_asyncio._loop import (
    TrioChildWatcher,
    TrioPolicy,
    _BasePolicy,
    _ChildWatcherBase,
    _PlatformDefaultPolicy,
    _trio_policy,
)


def test_package_imports():
    assert trio_asyncio.__version__


def test_trio_policy_types():
    assert isinstance(_trio_policy, TrioPolicy)
    assert issubclass(TrioPolicy, _BasePolicy)
    assert issubclass(TrioPolicy, _PlatformDefaultPolicy)
    # Outside Trio context, get_event_loop_policy() returns the pre-import
    # policy by design; the installed singleton is still TrioPolicy.
    assert isinstance(_trio_policy, _BasePolicy)


def test_trio_child_watcher_constructible():
    watcher = TrioChildWatcher()
    assert isinstance(watcher, _ChildWatcherBase)
    watcher.close()


@pytest.mark.skipif(sys.version_info < (3, 14), reason="3.14+ asyncio renames")
def test_uses_underscored_asyncio_names_on_3_14():
    # BaseDefaultEventLoopPolicy was renamed; AbstractChildWatcher removed.
    assert not hasattr(asyncio.events, "BaseDefaultEventLoopPolicy")
    assert _BasePolicy is asyncio.events._BaseDefaultEventLoopPolicy
    assert not hasattr(asyncio, "AbstractChildWatcher")
    assert _ChildWatcherBase is object


@pytest.mark.trio
async def test_open_loop_still_works():
    async with trio_asyncio.open_loop() as loop:
        assert asyncio.get_running_loop() is loop
