
+++++++
 Usage
+++++++

.. module:: trio_asyncio

Using :mod:`trio` from :mod:`asyncio`, or vice versa, requires two steps:

* :ref:`Set up a main loop that supports both <startup>`
* :ref:`Use cross-domain function calls <cross-calling>`

Because Trio and asyncio differ in some key semantics, most notably
how they handle tasks and cancellation, usually their domains are
strictly separated – i.e., you need to call a wrapper that translates
from one to the other. While trio-asyncio includes a wrapper that
allows you ignore that separation in some limited cases, you probably
should not use it in non-trivial programs.

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

Note that ``async_main`` here still must be a Trio-flavored async function!
:func:`trio_asyncio.run` is :func:`trio.run` plus an additional asyncio
context (which you can take advantage of using :func:`~trio_asyncio.aio_as_trio`).

Equivalently, wrap your main function (or any other code that needs to talk to
asyncio) in a :func:`trio_asyncio.open_loop` block::

    import trio
    import trio_asyncio

    async def async_main_wrapper(*args):
        async with trio_asyncio.open_loop() as loop:
            assert loop == asyncio.get_event_loop()
            await async_main(*args)

    trio.run(async_main_wrapper, *args)

In either case, within ``async_main``, calls to
:func:`asyncio.get_event_loop` will return the currently-running
`TrioEventLoop` instance. (Since asyncio code uses the result of
:func:`~asyncio.get_event_loop` as the default event loop in
effectively all cases, this means you don't need to pass ``loop=``
arguments around explicitly.)

`TrioEventLoop` has a few trio-asyncio specific methods in addition to
the usual `asyncio.AbstractEventLoop` interface; these are documented
in the appropriate sections below. In general you don't need to care
about any of them, though, as you can just use
:func:`~trio_asyncio.aio_as_trio` to run asyncio code. (See
:ref:`below <cross-calling>` for more details.)

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
``async with open_loop()`` / ``trio_asyncion.run()`` exits. trio-asyncio
will process all outstanding callbacks and terminate. As in asyncio,
callbacks which are added during this step will be ignored.

You cannot restart the loop, nor would you want to. You can always make
another loop if you need one.

.. _asyncio-loop:

Asyncio main loop
+++++++++++++++++

Sometimes you instead start with asyncio code which you wish to extend
with some Trio portions. The best-supported approach here is to
wrap your entire asyncio program in a Trio event loop. In other words,
you should transform this code::

    def main():
        loop = asyncio.get_event_loop()
        loop.run_until_complete(async_main())
    
or (Python 3.7 and later)::

    def main():
        asyncio.run(async_main())
    
to this::

    def main():
        trio_asyncio.run(trio_asyncio.aio_as_trio(async_main))

If your program makes multiple calls to ``run_until_complete()`` and/or
``run_forever()``, or if the call to :func:`asyncio.run` is hidden inside
a library you're using, then this may be a somewhat challenging transformation.
In such cases, you can instead keep the old approach (``get_event_loop()`` +
``run_until_complete()``) unchanged, and if you've imported ``trio_asyncio``
(and not changed the asyncio event loop policy) you'll still be able to use
:func:`~trio_asyncio.trio_as_aio` to run Trio code from within your
asyncio-flavored functions. This is referred to internally as a "sync loop"
(``SyncTrioEventLoop``), as contrasted with the "async loop" that you use
when you start from an existing Trio run. The sync loop is implemented using
the ``greenlet`` library to switch out of a Trio run that has not yet completed,
so it is less well-supported than the approach where you start in Trio.
But as of trio-asyncio 0.14.0, we do think it should generally work.

Compatibility issues
++++++++++++++++++++

Loop implementations
--------------------

There are replacement event loops for asyncio, such as ``uvloop``.
trio-asyncio is not compatible with them.

Multithreading
--------------

trio-asyncio monkey-patches asyncio's loop policy to be thread-local.
This lets you use ``uvloop`` in one thread while running ``trio_asyncio``
in another.

Interrupting the asyncio loop
-----------------------------

A trio-asyncio event loop created with :func:`open_loop` does not support
``run_until_complete`` or ``run_forever``. If you need these features,
you might be able to get away with using a "sync loop" as
explained :ref:`above <asyncio-loop>`, but it's better to refactor
your program so all of its async code runs within a single event loop
invocation. For example, you might replace::

    async def setup():
        pass # … start your services
    async def shutdown():
        pass # … terminate services and clean up
        loop.stop()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup)
    loop.run_forever()

with::

    stopped_event = trio.Event()
    async def setup():
        pass # … start your services
    async def cleanup():
        pass # … terminate services and clean up
    async def shutdown():
        stopped_event.set()

    async def async_main():
        await aio_as_trio(setup)()
        await stopped_event.wait()
        await aio_as_trio(cleanup)()
    trio_asyncio.run(async_main)

Detecting the current function's flavor
---------------------------------------

:func:`sniffio.current_async_library` correctly reports "asyncio" or
"trio" when called from a trio-asyncio program, based on the flavor of
function that's calling it.

However, this feature should generally not be necessary, because you
should know whether each function in your program is asyncio-flavored
or Trio-flavored. (The two have different semantics, especially
surrounding cancellation.) It's provided mainly so that your
trio-asyncio program can safely depend on libraries that use `sniffio`
to support both flavors. It can also be helpful if you want to assert
that you're in the mode you think you're in, using ::

    assert sniffio.current_async_library() == "trio"

(or ``"asyncio"``) to detect mismatched flavors while porting code
from asyncio to Trio.

.. _cross-calling:

---------------
 Cross-calling
---------------

First, a bit of background.

For historical reasons, calling an async function (of any
flavor) is a two-step process – that is, given ::

    async def proc():
        pass

a call to ``await proc()`` does two things:

  * ``proc()`` returns an ``awaitable``, i.e. something that has an
    ``__await__`` method.

  * ``await proc()`` then hooks this awaitable up to your event loop,
    so that it can do whatever combination of execution and cooperative
    blocking it desires. (Technically, ``__await__()`` returns an iterable,
    which is iterated until it has been exhausted, and each yielded object
    is sent through to the event loop.)

asyncio traditionally uses awaitables for indirect procedure calls,
so you often see the pattern::

    async def some_code():
        pass
    async def run(proc):
        await proc
    await run(some_code())

This method has a problem: it decouples creating the awailable from running
it. If you decide to add code to ``run`` that retries running ``proc`` when
it encounters a specific error, you're out of luck.

Trio, in contrast, uses (async) callables::

    async def some_code():
        pass
    async def run(proc):
        await proc()
    await run(some_code)

Here, calling ``proc`` multiple times from within ``run`` is not a problem.

trio-asyncio adheres to Trio conventions, but the
asyncio way is also supported when possible.

Calling asyncio from Trio
+++++++++++++++++++++++++

Wrap the callable, awaitable, generator, or iterator in
:func:`trio_asyncio.aio_as_trio`.

Thus, you can call an asyncio function from Trio as follows::

    async def aio_sleep(sec=1):
        await asyncio.sleep(sec)
    async def trio_sleep(sec=2):
        await aio_as_trio(aio_sleep)(sec)
    trio_asyncio.run(trio_sleep, 3)

or use as a decorator to pre-wrap::

    @aio_as_trio
    async def trio_sleep(sec=1):
        await asyncio.sleep(sec)
    trio_asyncio.run(trio_sleep, 3)

or pass an awaitable::

    async def aio_sleep(sec=1):
        await asyncio.sleep(sec)
    async def trio_sleep(sec=2):
        await aio_as_trio(aio_sleep(sec))
    trio_asyncio.run(trio_sleep, 3)

If you have a choice between ``aio_as_trio(foo)(bar)`` and
``aio_as_trio(foo(bar))``, choose the former. If ``foo()`` is an async
function defined with ``async def``, it doesn't matter; they behave
equivalently. But if ``foo()`` is a synchronous wrapper that does
anything before delegating to an async function, the first approach
will let the synchronous part of ``foo()`` determine the current
asyncio task, and the second will not.  The difference is relevant in
practice for popular libraries such as ``aiohttp``.

:func:`~trio_asyncio.aio_as_trio` also accepts `asyncio.Future`\s::

    async def aio_sleep(sec=1):
        await asyncio.sleep(sec)
        return 42
    async def trio_sleep(sec=2):
        f = aio_sleep(1)
        f = asyncio.ensure_future(f)
        r = await aio_as_trio(f)
        assert r == 42
    trio_asyncio.run(trio_sleep, 3)

as well as async iterators (such as async generators)::

    async def aio_slow():
        n = 0
        while True:
            await asyncio.sleep(n)
            yield n
            n += 1
    async def printer():
        async for n in aio_as_trio(aio_slow()):
            print(n)
    trio_asyncio.run(printer)

and async context managers::

    class AsyncCtx:
        async def __aenter__(self):
            await asyncio.sleep(1)
            return self
        async def __aexit__(self, *tb):
            await asyncio.sleep(1)
        async def delay(self, sec=1):
            await asyncio.sleep(sec)
    async def trio_ctx():
        async with aio_as_trio(AsyncCtx()) as ctx:
            print("within")
            await aio_as_trio(ctx.delay)(2)
    trio_asyncio.run(trio_ctx)

As you can see from the above example,
:func:`~trio_asyncio.aio_as_trio` handles wrapping the context entry
and exit, but it doesn't know anything about async methods that may
exist on the object to which the context evaluates. You still need to
treat them as :mod:`asyncio` methods and wrap them appropriately when
you call them.

Note that *creating* the async context manager or async iterator is
not itself an asynchronous process; i.e., ``AsyncCtx.__init__`` or
``__aiter__`` is a normal synchronous procedure. Only the
``__aenter__`` and ``__aexit__`` methods of an async context manager,
or the ``__anext__`` method of an async iterator, are
asynchronous. This is why you need to wrap the context manager or
iterator itself – unlike with a simple procedure call, you cannot
wrap the call for generating the context handler.

Thus, the following code **will not work**::

    async def trio_ctx():
        async with aio_as_trio(AsyncCtx)() as ctx:  # no!
            print("within")
	async for n in aio_as_trio(aio_slow)():  # also no!
	    print(n)

.. autofunction:: trio_asyncio.aio_as_trio

Too complicated?
----------------

There's also a somewhat-magic wrapper (:func:`trio_asyncio.allow_asyncio`)
which, as the name implies, allows you to directly call asyncio-flavored
functions from a function that is otherwise Trio-flavored. ::

    async def hybrid():
        await trio.sleep(1)
        await asyncio.sleep(1)
        print("Well, that worked")
    trio_asyncio.run(trio_asyncio.allow_asyncio, hybrid)

This method works for one-off code. However, there are a couple of
semantic differences between asyncio and Trio which
:func:`trio_asyncio.allow_asyncio` is unable to account for.
Additionally, the transparency support is only one-way; you can't
transparently call Trio from a function that's used by asyncio
callers. Thus, you really should not use it for "real" programs or
libraries.

.. autofunction:: trio_asyncio.allow_asyncio

Calling Trio from asyncio
+++++++++++++++++++++++++

Wrap the callable, generator, or iterator in
:func:`trio_asyncio.trio_as_aio`.

Thus, you can call a Trio function from asyncio as follows::

    async def trio_sleep(sec=1):
        await trio.sleep(sec)
    async def aio_sleep(sec=2):
        await trio_as_aio(trio_sleep)(sec)
    trio_asyncio.run(aio_as_trio, aio_sleep, 3)

or use a decorator to pre-wrap::

    @trio_as_aio
    async def aio_sleep(sec=2):
        await trio.sleep(sec)
    trio_asyncio.run(aio_as_trio, aio_sleep, 3)

In contrast to :func:`~trio_asyncio.aio_as_trio`, using an awaitable is not
supported because that's not an idiom Trio uses.

Calling a function wrapped with :func:`~trio_asyncio.trio_as_aio` returns a
regular :class:`asyncio.Future`. Thus, you can call it from a synchronous
context (e.g. a callback hook). Of course, you're responsible for catching
any errors – either arrange to ``await`` the future, or use
:meth:`~asyncio.Future.add_done_callback`::

    async def trio_sleep(sec=1):
        await trio.sleep(sec)
        return 42
    def cb(f):
        assert f.result == 42
    async def aio_sleep(sec=2):
        f = trio_as_aio(trio_sleep)(1)
        f.add_done_callback(cb)
        r = await f
        assert r == 42
    trio_asyncio.run(aio_as_trio, aio_sleep, 3)

You can wrap async context managers and async iterables just like with
:func:`~trio_asyncio.aio_as_trio`.

.. autofunction:: trio_as_aio

Trio background tasks
---------------------

If you want to start a Trio task that should be monitored by ``trio_asyncio``
(i.e. an uncaught error will propagate to, and terminate, the asyncio event
loop) instead of having its result wrapped in a :class:`asyncio.Future`, use
:func:`~trio_asyncio.run_trio_task`.

Multiple asyncio loops
++++++++++++++++++++++

trio-asyncio supports running multiple concurrent asyncio loops in different
Trio tasks in the same thread. You may even nest them.

This means that you can write a trio-ish wrapper around an asyncio-using
library without regard to whether the main loop or another library also use
trio-asyncio.

You can use the event loop's
:meth:`~trio_asyncio.BaseTrioEventLoop.autoclose` method to tell
trio-asyncio to auto-close a file descriptor when the loop
terminates. This setting only applies to file descriptors that have
been submitted to a loop's :meth:`~asyncio.loop.add_reader` or
:meth:`~asyncio.loop.add_writer` methods. As such, this method is
mainly useful for servers and should be used to supplement, rather
than replace, a ``finally:`` handler or a ``with closing(...):``
block.

Errors and cancellations
++++++++++++++++++++++++

Errors and cancellations are propagated almost-transparently.

For errors, this is straightforward: if a cross-called function terminates
with an exception, it continues to propagate out of the cross-call.

Cancellations are also propagated whenever possible. This means

* the task started with :func:`run_trio` is cancelled when you cancel
  the future which ``run_trio()`` returns

* if the task started with :func:`run_trio` is cancelled, 
  the future gets cancelled

* the future passed to :func:`run_aio_future` is cancelled when the Trio code
  calling it is cancelled

* However, when the future passed to :func:`run_aio_future` is cancelled (i.e.,
  when the task associated with it raises ``asyncio.CancelledError``), that
  exception is passed along unchanged.

  This asymmetry is intentional since the code that waits for the future
  often is not within the cancellation context of the part that
  created it. Cancelling the future would thus impact the wrong (sub)task.

-------------------------------
 asyncio feature support notes
-------------------------------

Deferred calls
++++++++++++++

:meth:`~asyncio.loop.call_soon` and friends work as usual.

Worker threads
++++++++++++++

:meth:`~asyncio.loop.run_in_executor` works as usual.

There is one caveat: the executor must be either ``None`` or an instance of
:class:`trio_asyncio.TrioExecutor`.

.. autoclass:: trio_asyncio.TrioExecutor

File descriptors
++++++++++++++++

:meth:`~asyncio.loop.add_reader` and
:meth:`~asyncio.loop.add_writer` work as usual, if you really
need them. Behind the scenes, these calls create a Trio task which waits
for readability/writability and then runs the callback.

You might consider converting code using these calls to native Trio tasks.

Signals
+++++++

:meth:`~asyncio.loop.add_signal_handler` works as usual.

Subprocesses
++++++++++++

:func:`~asyncio.create_subprocess_exec` and
:func:`~asyncio.create_subprocess_shell` work as usual.

You might want to convert these calls to use native Trio subprocesses.

Custom child watchers are not supported.

-------------------------
 Low-level API reference
-------------------------

.. autoclass:: trio_asyncio.BaseTrioEventLoop

   .. method:: run_aio_future(fut)
      :staticmethod:

      Alias for :meth:`trio_asyncio.run_aio_future`.

      This is a Trio-flavored async function.

   .. automethod:: run_aio_coroutine
   .. automethod:: trio_as_future
   .. automethod:: run_trio_task
   .. automethod:: synchronize
   .. automethod:: autoclose
   .. automethod:: no_autoclose
   .. automethod:: wait_stopped

.. autoclass:: trio_asyncio.TrioEventLoop
   :show-inheritance:

.. data:: trio_asyncio.current_loop

   A `contextvars.ContextVar` whose value is the `TrioEventLoop`
   created by the nearest enclosing ``async with open_loop():``
   block. This is the same event loop that will be returned by calls
   to :func:`asyncio.get_event_loop`.  If ``current_loop``'s value is
   ``None``, then :func:`asyncio.get_event_loop` will raise an error
   in Trio context. (Outside Trio context its value is always
   ``None`` and :func:`asyncio.get_event_loop` uses differnet logic.)

   It is OK to modify this if you want the current scope to use a different
   trio-asyncio event loop, but make sure not to let your modifications leak
   past their intended scope.

.. autofunction:: trio_asyncio.run_aio_future
.. autofunction:: trio_asyncio.run_aio_generator
.. autofunction:: trio_asyncio.run_aio_coroutine
.. autofunction:: trio_asyncio.run_trio
.. autofunction:: trio_asyncio.run_trio_task

.. autoexception:: trio_asyncio.TrioAsyncioDeprecationWarning
