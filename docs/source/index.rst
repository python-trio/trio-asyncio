.. documentation master file, created by
   sphinx-quickstart on Sat Jan 21 19:11:14 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.


========================================================================
trio-asyncio: A re-implementation of the asyncio mainloop on top of Trio
========================================================================

trio-asyncio is the library of choice for a Python program that
contains both `Trio <https://trio.readthedocs.io/en/stable/>`__ and
`asyncio` code.

Trio has native concepts of tasks and task cancellation. Asyncio is based
on callbacks and chaining Futures, albeit with nicer syntax, which make
handling of failures and timeouts fundamentally less reliable, especially in
larger programs. Thus, you really want to use Trio in your project.

On the other hand, there are quite a few robust libraries that have been
implemented using asyncio, while Trio's ecosystem is relatively younger. You
really don't want to re-invent any wheels in your project.

Thus, being able to use asyncio libraries from Trio is useful.
trio-asyncio enables you to do that, and more.

With trio-asyncio, you can:

* Incrementally convert an asyncio application to Trio. Start with a
  Trio mainloop, call your existing asyncio code, then successively
  convert procedures to Trio calling conventions.

* Use any asyncio-capable library in a Trio application.

* Use trio-asyncio as a building block for convincing other async-ish
  libraries (Twisted, Promise, …) to be compatible with Trio.

trio-asyncio is tested against the complete asyncio test suite as
shipped with each supported version of Python, although a small number of tests
fail due to our limited support for starting and stopping the same event
loop multiple times. It has also passed the test suite of some complex
asyncio libraries such as ``home-assistant``.

.. note:: trio-asyncio is most useful for *applications*: it works best
	  when you control the code that starts the event loop (such as
	  the call to :func:`asyncio.run`). If you're writing a *library* and
	  want to adopt a Trio-ish worldview without sacrificing asyncio
	  compatibility, you might find `anyio <https://anyio.readthedocs.io/en/latest/>`__
          helpful.

Helpful facts:

* Supported environments: Linux, MacOS, or Windows running some kind of Python
  3.7-or-better (either CPython or PyPy3 is fine). \*BSD and illumOS likely
  work too, but are untested.

* Install: ``python3 -m pip install -U trio-asyncio`` (or on Windows, maybe
  ``py -3 -m pip install -U trio-asyncio``). No compiler needed.

* Tutorial and reference manual: https://trio-asyncio.readthedocs.io

* Bug tracker and source code: https://github.com/python-trio/trio-asyncio

Inherited from `Trio <https://github.com/python-trio/trio>`__:

* Real-time chat: https://gitter.im/python-trio/general

* License: MIT or Apache 2, your choice

* Contributor guide: https://trio.readthedocs.io/en/latest/contributing.html

* Code of conduct: Contributors are requested to follow our `code of
  conduct <https://trio.readthedocs.io/en/latest/code-of-conduct.html>`_
  in all project spaces.

=====================
 trio-asyncio manual
=====================

.. toctree::
   :maxdepth: 2

   principles.rst
   usage.rst
   history.rst

====================
 Indices and tables
====================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
* :ref:`glossary`
