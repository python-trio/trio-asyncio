# This code implements basic asyncio compatibility

# Submodules are organized into the following layers, from highest to lowest;
# to avoid circular dependencies, submodules can only depend on other submodules
# in a strictly lower layer.
#
#                    nice facade: _adapter
# event loop dispatch and policy: _loop
#     event loop implementations: _async, _sync
#                event loop base: _base
#                      utilities: _handles, _util, _child, _deprecate, _version

from ._version import __version__  # noqa

from ._deprecate import TrioAsyncioDeprecationWarning
from ._util import run_aio_future, run_aio_generator
from ._base import BaseTrioEventLoop, TrioExecutor
from ._async import TrioEventLoop
from ._loop import (
    # main entry point:
    open_loop,
    # trio.run() + trio_asyncio.open_loop():
    run,
    # loop selection:
    current_loop,
    # forwarders to event loop methods:
    run_trio_task,
    run_trio,
    run_aio_coroutine,
)
from ._adapter import (
    aio_as_trio,
    trio_as_aio,
    # aliases for the above:
    asyncio_as_trio,
    trio_as_asyncio,
    # additional experimental goodie:
    allow_asyncio,
)

import importlib as _importlib
from . import _deprecate, _util

_deprecate.enable_attribute_deprecations(__name__)
__deprecated_attributes__ = {
    name: _deprecate.DeprecatedAttribute(
        _importlib.import_module("trio_asyncio._" + name.rstrip("_")),
        "0.11.0",
        issue=64,
        instead="an import from the top-level trio_asyncio package",
    )
    for name in ("adapter", "async_", "base", "child", "handles", "loop", "sync", "util")
}
__deprecated_attributes__.update(
    {
        name:
        _deprecate.DeprecatedAttribute(getattr(_loop, name), "0.11.0", issue=64, instead=None)
        for name in ("TrioPolicy", "TrioChildWatcher", "current_policy")
    }
)

# Provide aliases in the old place for names that moved between modules.
# Remove these when the non-underscore-prefixed module names are removed.
from . import _loop, _async
_async.open_loop = _loop.open_loop

_util.fixup_module_metadata(__name__, globals())
