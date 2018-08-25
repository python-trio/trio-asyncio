
+++++++
 Usage
+++++++

.. module: trio_asyncio

Using :mod:`trio` from :mod:`asyncio`, or vice versa, requires two steps:

* :ref:`Set up a main loop that supports both <startup>`
* :ref:`Use cross-domain function calls <cross-calling>`

Because :mod:`trio` and :mod:`asyncio` differ in some key semantics, most
notably how they handle tasks and cancellation, usually their domains are
strictly separated – i.e. you need to call a wrapper that translates from
one to the other. While :mod:`trio_asyncio` includes a wrapper that
allows you ignore that separation, you probably should not use it in
non-trivial programs.

.. _startup:

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

Within ``async_main``, calls to :func:`asyncio.get_event_loop` will return
the currently-running :class:`trio_asyncio.TrioEventLoop` instance. See
:ref:`below <cross-calling>` on how to use it to actually call async code.

Equivalently, wrap your main loop (or any other code that needs to talk to
asyncio) in a :func:`trio_asyncio.open_loop` call::

    import trio
    import trio_asyncio

    async def async_main_wrapper(*args):
        async with trio_asyncio.open_loop() as loop:
            assert loop == asyncio.get_event_loop()
            await async_main(*args)

    trio.run(async_main_wrapper, *args)

Within the ``async with`` block, an asyncio mainloop is active. Note that
unlike a traditional :mod:`asyncio` mainloop, this loop will be
automatically closed (not just stopped) when the end of the ``with
open_loop`` block is reached.

As this code demonstrates, you don't need to pass the ``loop`` argument
around, as :func:`asyncio.get_event_loop` will retrieve it when you're in
the loop's context.

.. autofunction:: trio_asyncio.open_loop

.. autofunction:: trio_asyncio.run

.. note:

   The ``async with open_loop()`` way of running ``trio_asyncio`` is
   useful for writing a library that can use ``asyncio`` code, supported by
   a "local" asyncio loop, without affecting the rest of your Trio program.

   Thus, under Trio you can have multiple concurrent ``asyncio`` loops.

Stopping
--------

The asyncio mainloop will be stopped automatically when the code within
``async with open_loop()`` / ``trio_asyncion.run()`` exits. Trio-asyncio
will process all outstanding callbacks and terminate. As in asyncio,
callbacks which are added during this step will be ignored.

You cannot restart the loop, nor would you want to.

Asyncio main loop.
++++++++++++++++++

If you'd like to keep your plain ``asyncio`` main loop and call Trio code
from it, there's one small problem: It won't work. Sorry.

There are two workarounds. One is to use ``asyncio``'s support for
threading and start a Trio loop in another thread. ``trio_asyncio`` might
learn some dedicated support for this mode, but basic ``trio`` and
``asyncio`` thread support is sufficient.

.. _native-loop:

The other way is to use a ``trio_asyncio`` main loop. You then run your
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

In real-world programs, this may be somewhat difficult. The good part is
that ``asyncio`` itself is transitioning towards the ``asyncio.run()`` way,
so the effort won't be wasted.

Compatibility issues
++++++++++++++++++++

Loop implementations
--------------------

There are replacements event loops for ``asyncio``, e.g. ``uvloop``.
``trio_asyncio`` is not compatible with them.

Multithreading
--------------

``trio_asyncio`` monkey-patches ``asyncio``'s loop policy to be thread-local.

This lets you use ``uvloop`` in one thread while running ``trio_asyncio``
in another.

Interrupting the asyncio loop
-----------------------------

Does not work: ``run_until_complete`` / ``run_forever`` are no longer
supported. You need to refactor your main loop. Broadly speaking, this
means to replace::

    async def setup():
        pass # … do whatever
    async def shutdown():
        pass # … do whatever
        loop.stop()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup)
    loop.run_forever()
        
with::

    async def setup():
        pass
    async def shutdown():
        pass # … do whatever
        stopped_event.set()

    async def async_main():
        await setup()
        await stopped_event.wait()
    trio_asyncio.run(trio_asyncio.run_asyncio, async_main)

``trio_asyncio`` still contains code for supporting ``run_until_complete``
and ``run_forever`` because it is required to run ``asyncio``'s testcases,
most of which require these calls.

However, to run this in production you'd need to jump through
a couple of hoops which are neither supported nor documented. Sorry.

Detecting the loop context
--------------------------

Short answer: You don't want to.

Long answer: You either are running within a call to :func:`trio_asyncio.run_asyncio`,
or you don't. There is no "maybe" here, and you shouldn't indiscriminately
call async code from both contexts – they have different semantics, esp.
concerning cancellation.

If you really need to do this, :func:`sniffio.current_async_library`
correctly reports "asyncio" when appropriate. (This requires Python 3.7
for :mod:`contextvars` support in :mod:`asyncio`.

.. _cross-calling:

---------------
 Cross-calling
---------------

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

You can also use the ``trio2aio`` function decorator::

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

If you need to call an asyncio-ish async context manager from Trio,
``loop.run_asyncio()`` also works::

    async with loop.run_asyncio(generate_context()) as ctx:
        await loop.run_asyncio(ctx.do_whatever)

As you can see from this example, the context that's returned is a "native"
asyncio context, so you still need to use ``run_asyncio()`` if you call its
methods.

Wrapping an async iterator also works::

    async def slow_nums():
        n = 0
        while True:
            asyncio.sleep(1)
            yield n
            n += 1

    async def trio_code(loop):
        async for n in loop.run_asyncio(slow_nums()):
            print(n)

    trio_asyncio.run(trio_code)

Note that in this case we're wrapping an async iterator, i.e. the object
returned by calling ``slow_nums``, not the function itself.

Too complicated?
++++++++++++++++

There's also a somewhat-magic wrapper which allows you to directly call
:mod:`asyncio` functions from :mod:`trio`.

.. autodoc: trio_asyncio.allow_asyncio

Calling Trio from asyncio
+++++++++++++++++++++++++

For basic async calls, pass the function and any arguments to
``loop.run_trio()``. This method returns a standard asyncio Future which
you can await, add callbacks to, or whatever.

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

``run_trio()`` is not itself an async function, so you can call it from a
synchronous context (e.g. a callback hook). However, you're responsible for
catching any errors – either await() the future, or use
``.add_done_callback()``.

If you want to start a task that shall be monitored by ``trio_asyncio``
(i.e. an uncaught error will propagate to, and terminate, the loop), use
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

Multiple asyncio loops
++++++++++++++++++++++

Trio-asyncio supports running multiple concurrent asyncio loops in the same
thread. You may even nest them.

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

* the task started with ``run_trio()`` is cancelled when you cancel
  the future which ``run_trio`` returns

* when the task started with ``run_trio()`` is cancelled, 
  the future gets cancelled

* the future used in ``run_future()`` is cancelled when the Trio code
  calling it is cancelled

* However, when the future passed to ``run_future()`` is cancelled (i.e.
  when the task associated with it raises ``asyncio.CancelledError``), that
  exception is passed along unchanged.

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

.. note:

   The class that watches for child processes must be an instance of
   :class:`trio_asyncio.TrioChildWatcher`. Trio-Asyncio enforces this.

