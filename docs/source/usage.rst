
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

Equivalently, wrap your main loop in a :func:`trio_asyncio.open_loop` call ::

    import trio_asyncio

    async def async_main(*args):
        async with trio_asyncio.open_loop() as loop:
            pass # async main code goes here

Within the ``async with`` block, the asyncio mainloop is active. You don't
need to pass the ``loop`` argument around, as
:func:`asyncio.get_event_loop` will do the right thing.

.. autofunction:: trio_asyncio.open_loop

.. autofunction:: trio_asyncio.run

Stopping
--------

The asyncio mainloop will be stopped automatically when the code within
``async with open_loop()`` exits. Trio-asyncio will process all outstanding
callbacks and terminate. As in asyncio, callbacks which are added during
this step will be ignored.

You cannot restart the loop, nor would you want to.

Asyncio main loop
+++++++++++++++++

Well …

What you really want to do is to use a Trio main loop, and run your asyncio
code in its context. In other words, you should transform this code::

    def main():
        loop = asyncio.get_event_loop()
        loop.run_until_complete(async_main())
    
to this::

    async def trio_main():
        async with trio_asyncio.open_loop() as loop:
            await trio.run_asyncio(async_main)

    def main():
        trio.run(trio_main)
    
You don't need to pass around the ``loop`` argument since trio remembers it
in its task structure: ``asyncio.get_event_loop()`` always works while
your program is executing an ``async with open_loop():`` block.

There is no Trio equivalent to ``loop.run_forever()``. The loop terminates
when you leave the ``async with`` block; it cannot be halted or restarted.

This mode is called an "async loop" or "asynchronous loop" because it is
started from an async (Trio) context.

Compatibility mode
------------------

You still can do things "the asyncio way": the to-be-replaced code from the
previous section still works. However, behind the scenes
a separate thread executes the Trio main loop. It runs in lock-step with
the thread that calls ``loop.run_forever()`` or
``loop.run_until_complete(coro)``. Signals etc. get
delegated if possible (except for [SIGCHLD]_). Thus, there should be no
concurrency issues.

Caveat: you may still experience problems, particularly if your code (or
a library you're calling) does not expect to run in a different thread.

.. [SIGCHLD] Python requires you to register SIGCHLD handlers in the main
   thread, but doesn't run them at all when waiting for another thread.
   
   Use :meth:`trio_asyncio.TrioChildWatcher.add_child_handler`,
   or :func:`trio_asyncio.wait_for_child` instead.

``loop.stop()`` tells the loop to suspend itself. You can restart it
with another call to ``loop.run_forever()`` or ``loop.run_until_complete(coro)``,
just as with a regular asyncio loop.

This mode is called a "sync loop" or "synchronous loop" because it is
started and used from a traditional synchronous Python context.

If you use a sync loop in a separate thread, you *must* stop and close it
before terminating the thread. Otherwise your thread will leak resources.

.. warning::
   Compatibility mode has been added to verify that various test suites,
   most notably the one from asyncio itself, continue to work. In a
   real-world program with a long-running asyncio mainloop, you *really*
   want to use a :ref:`Trio mainloop <trio-loop>` instead.

   The authors reserve the right to not fix compatibility mode bugs if that
   would negatively impact trio-asyncio's core functions.

.. autoclass:: trio_asyncio.sync.SyncTrioEventLoop

Stopping
--------

Call ``loop.stop()`` as usual.

Before stopping, the loop will process all outstanding callbacks.

Closing
-------

A synchronous loop starts a separate thread for running the asynchronous
part of your code. You **must** call ``loop.close()`` before abandoning the
loop.

.. note::

   This is not a problem in "normal" programs – when the program
   terminates, the loop dies along with it. However, when testing you don't
   want to leave 1000 asyncio threads lying around.
   
   This also applies in multi-threaded programs with more than one event loop.

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

Calling asyncio from Trio
+++++++++++++++++++++++++

Pass the function and any arguments to ``loop.run_asyncio()``. This method
conforms to Trio's standard task semantics.

::

    async def some_asyncio_code(foo):
        await asyncio.sleep(1)
        return foo*20
    
    res = await trio.run_asyncio(some_trio_code, 21)
    assert res == 420

.. autodoc: trio_asyncio.run_asyncio

If you already have a coroutine you need to await, call ``loop.run_coroutine()``:

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
:meth:`trio_asyncio.TrioEventLoop.add_writer`` methods. As such, this
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
:meth:`asyncio.AbstractEventLoop.add_writer`` work as usual, if you really
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

