
+++++++
 Usage
+++++++

.. module: trio_asyncio

Importing ``trio_asyncio`` replaces the default ``asyncio`` event loop with
``trio_asyncio``'s version. Thus it's mandatory to do that import before
using any ``asyncio`` code.

----------------------
 Startup and shutdown
----------------------

.. _trio-loop:

Trio main loop
++++++++++++++

Typically, you start with a Trio program which you need to extend with
asyncio code.

Before::

    import trio

    trio.run(async_main, *args)

After::

    import trio
    import trio_asyncio
    
    trio_asyncio.run(async_main, *args)

Equivalently, wrap your main loop (or any other code that needs to talk to
asyncio) in a :func:`trio_asyncio.open_loop` call ::

    import trio
    import trio_asyncio

    async def async_main_wrapper(*args):
        async with trio_asyncio.open_loop() as loop:
            assert loop == asyncio.get_event_loop()
            await async_main(*args)

    trio.run(async_main_wrapper, *args)

Within the ``async with`` block, an asyncio mainloop is active.

As this code demonstrates, you don't need to pass the ``loop`` argument
around, as :func:`asyncio.get_event_loop` will retrieve it when you're in
the loop's context.

.. note::

   Don't do both. The following code **will not work**::

        import trio
        import trio_asyncio

        async def async_main_wrapper(*args):
            async with trio_asyncio.open_loop() as loop:
                await async_main(*args)

        trio_asyncio.run(async_main_wrapper, *args)

.. autofunction:: trio_asyncio.open_loop

.. autofunction:: trio_asyncio.run

.. note::

   The ``async with open_loop()`` way of running ``trio_asyncio`` is
   intended to transparently allow a library to use ``asyncio`` code,
   supported by a "local" asyncio loop, without affecting the rest of your
   Trio program.

   However, currently this doesn't work because Trio does not yet support
   ``contextvars``. Progress on this limitation is tracked in `this issue
   on github <https://github.com/python-trio/trio-asyncio/issues/9>`_.

Stopping
--------

The asyncio mainloop will be stopped automatically when the code within
``async with open_loop()`` / ``trio_asyncion.run()`` exits. Trio-asyncio
will process all outstanding callbacks and terminate. As in asyncio,
callbacks which are added during this step will be ignored.

You cannot restart the loop, nor would you want to.

Asyncio main loop.
++++++++++++++++++

Doesn't work. However: read on.

.. _native-loop:

What you really want to do is to use a Trio main loop. You then run your
complete asyncio code in its context. In other words, you should transform
this code::

    def main():
        loop = asyncio.get_event_loop()
        loop.run_until_complete(async_main())
    
or (Python 3.7 ++)::

    def main():
        asyncio.run(async_main())
    
to this::

    async def trio_main():
        await trio_asyncio.run_asyncio(async_main)

    def main():
        trio_asyncio.run(trio_main)

That's all you need to to to support cross-calling from asyncio to trio
code, or vice versa. You still need to use adapters, though:
:ref:`see below <cross-calling>` for details.

If your program's start-up code consists of more than one
``loop.run_until_complete`` or ``loop.run_forever`` calls, and/or it
accesses the asyncio mainloop outside of these two calls, you may have to
do some refactoring. Sorry about that.

Compatibility mode
++++++++++++++++++

… or, running ``trio_asyncio`` on top of an unmodified ``asyncio`` main loop.

Unfortunately, we had to discontinue support for this mode. The code was
too intrusive and not particularly stable, caused problems with debugging,
and crashed ``asyncio`` when ``trio_asyncio`` was imported after starting
the asyncio mainloop.

``trio_asyncio`` still contains the code, as it is required to run
``asyncio``'s testcases, which pretty much require synchronous mode.
However, if you want to run this in production you'd neet to jump through
various hoops which are neither supported nor documented. Sorry.

.. _cross-calling:

---------------
 Cross-calling
---------------

Calling Trio from asyncio
+++++++++++++++++++++++++

Pass the function and any arguments to ``loop.run_trio()``. This method
returns a standard asyncio Future which you can await, add callbacks to,
or whatever.

::

    async def some_trio_code(foo):
        await trio.sleep(1)
        return foo*2
    
    future = loop.run_trio(some_trio_code, 21)
    res = await future
    assert res == 42

You can also use the ``aio2trio`` decorator::

    @aio2trio
    async def some_trio_code(self, foo):
        await trio.sleep(1)
        return foo+33

    res = await some_trio_code(9)
    assert res == 42

.. autodoc: trio_asyncio.adapter.aio2trio

.. autodoc: trio_asyncio.adapter.aio2trio_task

It is OK to call ``run_trio()``, or a decorated function or method, from a
synchronous context (e.g. a callback hook). However, you're responsible for
catching any errors – either await() the future, or use
``.add_done_callback()``.

If you want to start a task that shall be monitored by trio (i.e. an
uncaught error will propagate and terminate the loop), use
``run_trio_task()`` instead.

.. autodoc: trio_asyncio.adapter.aio2trio_task

If you need to call a Trio-style async context manager from asyncio, use
``loop.wrap_trio_context()``::

    async with loop.wrap_trio_context(context()) as ctx:
        await loop.run_trio(ctx.do_whatever)

As you can see from this example, the context that's returned is a "native"
Trio context, so you still need to use ``run_trio()`` if you call its
methods.

.. autodoc: trio_asyncio.wrap_trio_context

Calling asyncio from Trio
+++++++++++++++++++++++++

Pass the function and any arguments to ``loop.run_asyncio()``. This method
conforms to Trio's standard task semantics.

:func:`trio_asyncio.run_asyncio` is a shortcut for
``asyncio.get_event_loop().run_asyncio``.

::

    async def some_asyncio_code(foo):
        await asyncio.sleep(1)
        return foo*20
    
    res = await trio_asyncio.run_asyncio(some_trio_code, 21)
    assert res == 420

.. autodoc: trio_asyncio.run_asyncio

If you already have a coroutine you need to await, call ``loop.run_coroutine()``.

:func:`trio_asyncio.run_coroutine` is a shortcut for
``asyncio.get_event_loop().run_coroutine``.

::

    async def some_asyncio_code(foo):
        await asyncio.sleep(1)
        return foo*20
    
    fut = asyncio.ensure_future(some_asyncio_code(21))
    res = await trio.run_coroutine(fut)
    assert res == 420

.. autodoc: trio_asyncio.run_coroutine

You can also use the ``trio2aio`` decorator::

    @trio2aio
    async def some_asyncio_code(self, foo):
        await asyncio.sleep(1)
        return foo+33

    # then, within a trio function
    res = await some_asyncio_code(9)
    assert res == 42

.. autodoc: trio_asyncio.trio2aio

If you already have a future, you can wait for it directly.

.. autodoc: trio_asyncio.run_future

:func:`trio_asyncio.run_future` does not require a running trio-asyncio
main loop.

If you need to call a Trio-style async context manager from asyncio,
``loop.run_asyncio()`` works::

    async with loop.run_asyncio(generate_context()) as ctx:
        await loop.run_asyncio(ctx.do_whatever)

As you can see from this example, the context that's returned is a "native"
asyncio context, so you still need to use ``run_asyncio()`` if you call its
methods.

Multiple asyncio loops
++++++++++++++++++++++

Trio-asyncio supports running multiple concurrent asyncio loops in the same
thread. You may even nest them (if they're asynchronous, of course).

This means that you can write a trio-ish wrapper around an asyncio-using
library without regard to whether the main loop or another library also use
trio-asyncio.

You can use :meth:`trio_asyncio.TrioEventLoop.autoclose` to tell trio-asyncio to auto-close
a file descriptor when the loop terminates. This setting only applies to
file descriptors that have been submitted to a loop's
:meth:`trio_asyncio.TrioEventLoop.add_reader` or
:meth:`trio_asyncio.TrioEventLoop.add_writer` methods. As such, this
method is mainly useful for servers and should be used as supplementing,
but not replacing, a ``finally:`` handler or an ``async with aclosing():``
block.

.. autodoc: trio_asyncio.TrioEventLoop.autoclose

Errors and cancellations
++++++++++++++++++++++++

Errors and cancellations are propagated almost-transparently.

For errors, this is straightforward.

Cancellations are also propagated whenever possible. This means

* the code called from ``run_trio()`` is cancelled when you cancel
  the future it returns

* when the code called from ``run_trio()`` is cancelled, 
  the future it returns gets cancelled

* the future used in ``run_future()`` is cancelled when the Trio code
  calling it is stopped

* However, when the future passed to ``run_future()`` is cancelled (i.e.
  when the code inside raises ``asyncio.CancelledError``), that exception is
  passed along unchanged.

  This asymmetry is intentional since the code that waits for the future
  often is not within the cancellation context of the part that
  created it. Cancelling the future would thus impact the wrong (sub)task.

----------------
 Deferred Calls
----------------

:meth:`asyncio.AbstractEventLoop.call_soon` and friends work as usual.

----------------
 Worker Threads
----------------

:meth:`asyncio.AbstractEventLoop.run_in_executor` works as usual.

There is one caveat: the executor must be either ``None`` or an instance of
:class:`trio_asyncio.TrioExecutor`. The constructor of this class accepts one
argument: the number of workers.

------------------
 File descriptors
------------------

:meth:`asyncio.AbstractEventLoop.add_reader` and
:meth:`asyncio.AbstractEventLoop.add_writer` work as usual, if you really
need them. Behind the scenes, these calls create a Trio task which runs the
callback.

You might consider converting code using these calls to native Trio tasks.

---------
 Signals
---------

:meth:`asyncio.AbstractEventLoop.add_signal_handler` works as usual.

------------
Subprocesses
------------

:func:`asyncio.create_subprocess_exec` and
:func:`asyncio.create_subprocess_shell` work as usual.

You might want to convert these calls to native Trio subprocesses.

.. note::

   The class that watches for child processes must be an instance of
   :class:`trio_asyncio.TrioChildWatcher`. Trio-Asyncio enforces this.

   Note that if you use compatibility mode, Python's ``SIGCHLD`` handling
   **will not work** anyway: The signal handler must run in the main
   thread, which is blocked waiting for the result of the current
   invocation of :meth:`trio_asyncio.sync.SyncTrioEventLoop.run_until_complete` call.

