Release history
===============

.. currentmodule:: trio_asyncio

.. towncrier release notes start

trio-asyncio 0.12.0 (2021-01-04)
--------------------------------

Bugfixes
~~~~~~~~

- On Python versions with native contextvars support (3.7+), a Trio task
  started from asyncio context (using :func:`trio_as_aio`,
  :meth:`~BaseTrioEventLoop.trio_as_future`, etc) will now properly
  inherit the contextvars of its caller.  Also, if the entire
  trio-asyncio loop is cancelled, such tasks will no longer let
  `trio.Cancelled` exceptions leak into their asyncio caller. (`#76 <https://github.com/python-trio/trio-asyncio/issues/76>`__)
- Previously, cancelling the context surrounding an :func:`open_loop`
  block might cause a deadlock in some cases. The ordering of operations
  during loop teardown has been improved, so this shouldn't happen
  anymore. (`#81 <https://github.com/python-trio/trio-asyncio/issues/81>`__)

Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

A number of functions deprecated since 0.10.0 are now removed:

================================================= =============================================
  Removed                                           Replacement
================================================= =============================================
``wrap_generator(proc, *args)``                   :func:`aio_as_trio(proc(*args))<aio_as_trio>`
``run_iterator(aiter)``                           :func:`aio_as_trio(aiter)<aio_as_trio>`
``trio2aio``                                      :func:`aio_as_trio`
``aio2trio``                                      :func:`trio_as_aio`
``run_future`` ``TrioEventLoop.run_future``       :func:`run_aio_future`
``run_coroutine`` ``TrioEventLoop.run_coroutine`` :func:`run_aio_coroutine`
``wrap_trio_context(ctx)``                        :func:`trio_as_aio(ctx)<trio_as_aio>`
``TrioEventLoop.run_trio(proc, *args)``           :func:`trio_as_aio(proc)(*args)<trio_as_aio>`
``run_asyncio(proc, *args)``                      :func:`aio_as_trio(proc)(*args)<aio_as_trio>`
================================================= =============================================

Miscellaneous
~~~~~~~~~~~~~

- ``trio-asyncio`` now requires Trio 0.15. Support for Python < 3.6 has been removed. (`#82 <https://github.com/python-trio/trio-asyncio/issues/82>`__)

- No more ``TrioDeprecationWarning`` about ``trio.hazmat``. (`#82 <https://github.com/python-trio/trio-asyncio/issues/82>`__)


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

- :func:`trio_asyncio.run` now properly returns whatever was returned by
  the async function it ran, like :func:`trio.run` does. (`#57 <https://github.com/python-trio/trio-asyncio/issues/57>`__)

- Replace uses of deprecated ``trio.open_cancel_scope()`` with `trio.CancelScope`.

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

Bugfixes
~~~~~~~~

- Defer creating an asyncio coroutine until asyncio mode is actually entered. (`#40 <https://github.com/python-trio/trio-asyncio/issues/40>`__)

trio-asyncio 0.9.0 (2018-08-31)
-------------------------------

Features
~~~~~~~~

- **Major reorganization:** The main entry point for calling asyncio
  from trio is now the :func:`trio_asyncio.aio_as_trio` adapter.
  Instead of calling :func:`asyncio.get_event_loop`, directly access the
  contextvar ``trio_aio_loop`` (aka :data:`trio_asyncio.current_loop`). (`#36 <https://github.com/python-trio/trio-asyncio/issues/36>`__)

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

trio-asyncio 0.8.2 (2018-08-25)
-------------------------------

Features
~~~~~~~~

- :func:`sniffio.current_async_library` in a trio-asyncio program now returns
  the correct value for the current mode (``"trio"`` or ``"asyncio"``).

trio-asyncio 0.8.1 (2018-08-25)
-------------------------------

Features
~~~~~~~~

- `trio_asyncio` now contains an :func:`allow_asyncio` wrapper which allows you to
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

- While the test suite still requires Python 3.6, :mod:`trio_asyncio` itself
  now works on Python 3.5.3 and later. (`#33
  <https://github.com/python-trio/trio-asyncio/issues/33>`__)

- ``TrioEventLoop.run_asyncio()`` now supports wrapping async iterators
  and async context managers, in addition to its existing support for async
  functions.

trio-asyncio 0.8.0 (2018-08-03)
-------------------------------

* Add ``TrioEventLoop.run_iterator()`` as an alias for ``run_generator()``.

* Add support for Python 3.7 via a monkey-patch to
  :func:`asyncio.set_event_loop_policy`. (`#23
  <https://github.com/python-trio/trio-asyncio/issues/23>`__)

* Deprecate the use of "compatibility mode" / "sync event loops", except
  as a tool for running the test suites of existing asyncio projects.

trio-asyncio 0.7.5 (2018-07-23)
-------------------------------

* Use a contextvar to represent the current trio-asyncio loop, rather
  than the deprecated ``trio.TaskLocal``.

* Use the ``outcome`` library rather than the deprecated ``trio.hazmat.Result``.

* Better handle errors in wrapped async generators.

trio-asyncio 0.7.0 (2018-03-27)
-------------------------------

* The ``@trio2aio`` and ``@aio2trio`` decorators now can be used to decorate
  both async generator functions and async functions that take keyword
  arguments.

* :func:`open_loop` now takes an optional ``queue_len=`` parameter to specify
  the length of the internal callback queue (for performance tuning).

* Add :meth:`BaseTrioEventLoop.synchronize`.

* Monkey-patch :func:`asyncio.get_event_loop_policy` and
  :func:`asyncio.get_event_loop` so trio-asyncio works correctly in
  multithreaded programs that use a different asyncio event loop in
  other threads.

* Add ``wrap_generator()`` and ``run_generator()`` which adapt an asyncio-flavored
  async generator to be used from Trio code.

trio-asyncio 0.5.0 (2018-02-20)
-------------------------------

* Support contextvars on Python 3.7 and later.

* Support waiting for child processes even though Trio doesn't (yet).

trio-asyncio 0.4.2 (2018-02-12)
-------------------------------

* Add :func:`trio_asyncio.run`.

* Fix a deadlock in ``SyncTrioEventLoop``. Encourage people to use the
  async ``TrioEventLoop`` instead.

trio-asyncio 0.4.1 (2018-02-08)
-------------------------------

* Add ``TrioEventLoop.run_task()`` as an entry point for running Trio code
  in a context that allows asyncio calls, for use when neither a Trio nor
  an asyncio event loop is running.

trio-asyncio 0.4.0 (2018-02-07)
-------------------------------

* Add support for async loops (:func:`open_loop`) and encourage their use.
  Numerous functions renamed.
  
trio-asyncio 0.3.0 (2017-10-17)
-------------------------------

* Initial release.

