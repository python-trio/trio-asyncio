Release history
===============

.. currentmodule:: trio_asyncio

.. towncrier release notes start

Trio_Asyncio 0.10.1 (2019-07-04)
--------------------------------

Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Deprecations

  ``trio.open_cancel_scope`` is deprecated: replaced with `trio.CancelScope`.


Trio_Asyncio 0.9.0 (2018-08-31)
-------------------------------

Features
~~~~~~~~

- Major reorganization

  The main entry point for calling asyncio from trio is now the
  :func:`trio_asyncio.aio_as_trio` adapter.

  Instead of calling :func:`asyncio.get_event_loop`, directly access the
  contextvar ``trio_aio_loop`` (aka ``trio_asyncio.adapter.current_loop``). (`#36 <https://github.com/python-trio/trio-asyncio/issues/36>`__)


Bugfixes
~~~~~~~~

- Defer creating an asyncio coroutine until asyncio mode is actually entered. (`#40 <https://github.com/python-trio/trio-asyncio/issues/40>`__)
- Replace deprecated ``trio.Queue`` with new channels, requiring Trio 0.9 or later. (`#49 <https://github.com/python-trio/trio-asyncio/issues/49>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Deprecations

  ``run_asyncio`` is deprecated: replace with a :func:`aio_as_trio` wrapper.

  ``trio2aio`` is deprecated: replace with :func:`aio_as_trio`.

  ``run_future`` and ``TrioEventLoop.run_future`` are deprecated: replace with ``run_aio_future``.

  ``run_coroutine`` and ``TrioEventLoop.run_coroutine`` are deprecated: replace with ``run_aio_coroutine``.

  ``TrioEventLoop.wrap_generator`` is deprecated: replace with a :func:`aio_as_trio` wrapper.

  ``TrioEventLoop.run_iterator`` is deprecated: replace with :func:`aio_as_trio`. (`#36 <https://github.com/python-trio/trio-asyncio/issues/36>`__)


Trio_Asyncio 0.8.1 (2018-08-25)
-------------------------------

Features
~~~~~~~~

- `trio_ayncio` now contains an `allow_asyncio` wrapper which allows you to
  seamlessly mix asyncio and trio semantics:: from trio_asyncio import run
  allow_asyncio async def main(): print("Sleeping 1") await asyncio.sleep(1)
  print("Sleeping 2") await trio.sleep(1) run(allow_asyncio, main) The problem
  with this solution is that Trio's cancellations will no longer be converted
  to asyncio's `CancelledError` within asyncio code. This may or may not be an
  issue for your code. (`#30
  <https://github.com/python-trio/trio-asyncio/issues/30>`__)


Bugfixes
~~~~~~~~

- The test suite requires Python 3.6. :mod:`trio_asyncio` itself requires
  Python 3.5.3. (`#33
  <https://github.com/python-trio/trio-asyncio/issues/33>`__)
