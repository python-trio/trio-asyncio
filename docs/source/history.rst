Release history
===============

.. currentmodule:: trio_asyncio

.. towncrier release notes start

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
