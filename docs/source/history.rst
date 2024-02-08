Release history
===============

.. currentmodule:: trio_asyncio

.. towncrier release notes start

trio-asyncio 0.14.0 (2024-02-07)
--------------------------------

Features
~~~~~~~~

- trio-asyncio now implements its :ref:`synchronous event loop <asyncio-loop>`
  (which is used when the top-level of your program is an asyncio call such as
  :func:`asyncio.run`, rather than a Trio call such as :func:`trio.run`)
  using the ``greenlet`` library rather than a separate thread. This provides
  some better theoretical grounding and fixes various edge cases around signal
  handling and other integrations; in particular, recent versions of IPython
  will no longer crash when importing trio-asyncio. Synchronous event loops have
  been un-deprecated with this change, though we still recommend using an
  async loop (``async with trio_asyncio.open_loop():`` from inside a Trio run)
  where possible. (`#137 <https://github.com/python-trio/trio-asyncio/issues/137>`__)
- trio-asyncio now better respects cancellation semantics for
  asyncio-to-Trio transitions. The asyncio caller now will not propagate
  cancellation until the Trio callee actually terminates, and only if
  the Trio callee terminates by cancellation (rather than, for example,
  finishing normally because the cancel arrived too late). Additionally,
  we no longer immediately cancel all Trio tasks started from asyncio
  context if the entire :func:`open_loop` is cancelled; they only become
  cancelled when their asyncio caller is cancelled, or when the body of
  the :func:`open_loop` terminates. (`#140 <https://github.com/python-trio/trio-asyncio/issues/140>`__)


Bugfixes
~~~~~~~~

- trio-asyncio no longer applies a limit to the maximum number of
  asyncio callbacks (including new task creations) that can be enqueued
  near-simultaneously. Previously the default limit was 10,000. A limit
  may still be requested using the *queue_len* parameter to
  :func:`open_loop`, but this is discouraged because there is no way
  to fail gracefully upon exceeding the limit; it will most likely just
  crash your program. (`#130 <https://github.com/python-trio/trio-asyncio/issues/130>`__)
- Fix an issue where a call to ``TrioEventLoop.call_exception_handler()`` after
  the loop was closed would attempt to call a method on ``None``. This pattern
  can be encountered if an ``aiohttp`` session is garbage-collected without being
  properly closed, for example. (`#134 <https://github.com/python-trio/trio-asyncio/issues/134>`__)


trio-asyncio 0.13.0 (2023-12-01)
--------------------------------

Features
~~~~~~~~

- Exiting an ``async with trio_asyncio.open_loop():`` block now cancels
  any asyncio tasks that are still running in the background, like
  :func:`asyncio.run` does, so that they have a chance to clean up
  resources by running async context managers and ``finally``
  blocks. Previously such tasks would simply be abandoned to the garbage
  collector, resulting in potential deadlocks and stderr spew. Note that,
  like :func:`asyncio.run`, we *do* still abandon any tasks that are
  started during this finalization phase and outlive the existing tasks.
  (`#91 <https://github.com/python-trio/trio-asyncio/issues/91>`__)

Bugfixes
~~~~~~~~

- A deadlock will no longer occur if :func:`trio_asyncio.open_loop`
  is cancelled before its first checkpoint. We also now cancel and wait on
  all asyncio tasks even if :func:`~trio_asyncio.open_loop` terminates due
  to an exception that was raised within the ``async with`` block. (`#115 <https://github.com/python-trio/trio-asyncio/issues/115>`__)
- Uncaught exceptions from asyncio tasks will now propagate out of the
  :func:`trio_asyncio.open_loop` call.  This has always been the
  documented behavior, but didn't actually work before.
  (`#121 <https://github.com/python-trio/trio-asyncio/issues/121>`__)
- Use of ``loop.add_reader()`` or ``loop.add_writer()`` with a socket object
  (rather than a file descriptor) will no longer potentially produce spurious
  uncaught exceptions if the socket is closed in the reader/writer callback.
  (`#121 <https://github.com/python-trio/trio-asyncio/issues/121>`__)

Miscellaneous
~~~~~~~~~~~~~

- ``trio-asyncio`` now requires Trio 0.22 and does not produce deprecation warnings.
  Python 3.12 is now supported. Python 3.6 and 3.7 are no longer supported. (`#121 <https://github.com/python-trio/trio-asyncio/issues/121>`__)
- trio-asyncio now indicates its presence to `sniffio` using the
  ``sniffio.thread_local`` interface that is preferred since sniffio
  v1.3.0. This should be less likely than the previous approach to cause
  :func:`sniffio.current_async_library` to return incorrect results due
  to unintended inheritance of contextvars.
  (`#123 <https://github.com/python-trio/trio-asyncio/issues/123>`__)


trio-asyncio 0.12.0 (2021-01-07)
--------------------------------

Bugfixes
~~~~~~~~

- trio-asyncio now cancels any Trio tasks that were started inside a trio-asyncio
  loop (using e.g. :func:`trio_as_aio`) before it allows the trio-asyncio loop
  to close. This should resolve some cases of deadlocks and "RuntimeError: Event loop
  is closed" when an ``async with open_loop():`` block is cancelled. (`#89 <https://github.com/python-trio/trio-asyncio/issues/89>`__)
- :func:`asyncio.get_running_loop` will now return the trio-asyncio event loop
  (if running), instead of failing with :exc:`RuntimeError`. (`#99 <https://github.com/python-trio/trio-asyncio/issues/99>`__)
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

