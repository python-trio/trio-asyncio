Release history
===============

.. currentmodule:: trio_asyncio

.. towncrier release notes start

trio-asyncio 0.11.0 (2020-03-09)
--------------------------------

Features
~~~~~~~~

- Substantially reorganize monkeypatching for asyncio event loop and
  event loop policy accessors, fixing support for Python 3.8. Also, stop
  using features deprecated in Trio 0.12. (`#66 <https://github.com/python-trio/trio-asyncio/issues/66>`__)

Bugfixes
~~~~~~~~

- Calling ``loop.stop`` manually no longer causes a deadlock when
  exiting the context of ``trio_asyncio.open_loop`` (`#58 <https://github.com/python-trio/trio-asyncio/issues/58>`__)

Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- The non-underscore-prefixed names of trio-asyncio submodules (``trio_asyncio.loop``,
  ``trio_asyncio.adapter``, etc) have been deprecated; public names should be
  imported from ``trio_asyncio`` directly.

  ``trio_asyncio.current_policy``, ``trio_asyncio.TrioChildWatcher``,
  and ``trio_asyncio.TrioPolicy`` have been deprecated with no
  replacement.  ``current_policy`` is no longer used at all, and the
  other two are singletons that can't be customized so there's no reason
  to make them publicly visible.

  A number of functions which were already documented as deprecated now
  raise the new :exc:`~trio_asyncio.TrioAsyncioDeprecationWarning` where
  previously they provided either no runtime warning or a generic
  :exc:`DeprecationWarning`. (`#64 <https://github.com/python-trio/trio-asyncio/issues/64>`__)

trio-asyncio 0.10.0 (2018-12-09)
--------------------------------

Bugfixes
~~~~~~~~

- Replace deprecated ``trio.Queue`` with new channels, requiring Trio 0.9 or later. (`#49 <https://github.com/python-trio/trio-asyncio/issues/49>`__)

trio-asyncio 0.9.1 (2018-09-06)
-------------------------------

Features
~~~~~~~~

- **Major reorganization:** The main entry point for calling asyncio
  from trio is now the :func:`trio_asyncio.aio_as_trio` adapter.
  Instead of calling :func:`asyncio.get_event_loop`, directly access the
  contextvar ``trio_aio_loop`` (aka :var:`trio_asyncio.adapter.current_loop`). (`#36 <https://github.com/python-trio/trio-asyncio/issues/36>`__)

Bugfixes
~~~~~~~~

- Defer creating an asyncio coroutine until asyncio mode is actually entered. (`#40 <https://github.com/python-trio/trio-asyncio/issues/40>`__)

Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- ``run_asyncio()`` is deprecated: replace with a :func:`aio_as_trio` wrapper.

  ``trio2aio()`` is deprecated: replace with :func:`aio_as_trio`.

  ``run_future()`` and ``TrioEventLoop.run_future()`` are deprecated:
  replace with :func:`run_aio_future`.

  ``run_coroutine()`` and ``TrioEventLoop.run_coroutine()`` are
  deprecated: replace with :func:`run_aio_coroutine`.

  ``TrioEventLoop.wrap_generator()`` is deprecated: replace with a
  :func:`aio_as_trio` wrapper.

  ``TrioEventLoop.run_iterator()`` is deprecated: replace with
  :func:`aio_as_trio`. (`#36
  <https://github.com/python-trio/trio-asyncio/issues/36>`__)

trio-asyncio 0.8.4 (2018-08-25)
-------------------------------

trio-asyncio 0.8.3 (2018-08-25)
-------------------------------

trio-asyncio 0.8.2 (2018-08-25)
-------------------------------

trio-asyncio 0.8.1 (2018-08-25)
-------------------------------

trio-asyncio 0.8.0 (2018-08-03)
-------------------------------

trio-asyncio 0.8.1 (2018-08-25)
-------------------------------

Features
~~~~~~~~

- `trio_asyncio` now contains an `allow_asyncio` wrapper which allows you to
  seamlessly mix asyncio and trio semantics::

      import asyncio
      import trio
      from trio_asyncio import run, allow_asyncio
      async def main():
          print("Sleeping 1")
          await asyncio.sleep(1)
          print("Sleeping 2")
          await trio.sleep(1)
      run(allow_asyncio, main)

  The problem with this solution is that Trio's cancellations will no
  longer be converted to asyncio's `~asyncio.CancelledError` within asyncio
  code. This may or may not be an issue for your code. (`#30
  <https://github.com/python-trio/trio-asyncio/issues/30>`__)


Bugfixes
~~~~~~~~

- The test suite requires Python 3.6. :mod:`trio_asyncio` itself requires
  Python 3.5.3. (`#33
  <https://github.com/python-trio/trio-asyncio/issues/33>`__)
