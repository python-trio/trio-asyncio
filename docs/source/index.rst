.. documentation master file, created by
   sphinx-quickstart on Sat Jan 21 19:11:14 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.


========================================================================
trio-asyncio: A re-implementation of the asyncio mainloop on top of Trio
========================================================================

Trio-Asyncio is *the* library of choice for a Python program that 
contains both `trio`_ and `asyncio`_ code.

.. _asyncio: https://docs.python.org/3/library/asyncio.html

With trio-asyncio, you can:

* incrementally convert your code to Trio. Start with a Trio mainloop, call
  your existing asyncio code, then successively convert procedures to Trio
  conventions.

* use any asyncio-capable library.

* use trio-asyncio as a building block for convincing other async-ish
  libraries (Twisted, Promise, …) to be compatible with Trio.

Trio-Asyncio passes the complete Python 3.6 test suite for asyncio. The
test suites for some well-known libraries like aiohttp also Just Work.

There's also compatibility code for not running the asyncio loop
continuously, as in repeated run_until_complete / run_forever-and-call-stop
calls. This mode will probably not be supported forever, but for now it works
well.

Helpful facts:

* Supported environments: Linux, MacOS, or Windows running some kind of Python
  3.5-or-better (either CPython or PyPy3 is fine). \*BSD and illumus likely
  work too, but are untested.

* Install: ``python3 -m pip install -U trio-asyncio`` (or on Windows, maybe
  ``py -3 -m pip install -U trio-asyncio``). No compiler needed.

* Tutorial and reference manual: https://trio-asyncio.readthedocs.io

* Bug tracker and source code: https://github.com/python-trio/trio-asyncio

Inherited from `Trio <https://github.com/python-trio/trio>`_:

* Real-time chat: https://gitter.im/python-trio/general

* License: MIT or Apache 2, your choice

* Contributor guide: https://trio.readthedocs.io/en/latest/contributing.html

* Code of conduct: Contributors are requested to follow our `code of
  conduct <https://trio.readthedocs.io/en/latest/code-of-conduct.html>`_
  in all project spaces.

.. toctree::
   :maxdepth: 2

   rationale.rst
   usage.rst
   history.rst

====================
 Indices and tables
====================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
* :ref:`glossary`
