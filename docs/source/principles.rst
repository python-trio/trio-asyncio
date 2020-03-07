.. currentmodule:: trio_asyncio

++++++++++++
 Principles
++++++++++++

--------------------------------------
 Async function "flavors"
--------------------------------------

As you might recall from the discussion of async "sandwiches" in the
`Trio tutorial
<https://trio.readthedocs.io/en/stable/tutorial.html#async-sandwich>`__,
every async function ultimately must do its useful work by directly or
indirectly calling back into the same async library (such as asyncio
or Trio) that's managing the currently running event loop. If a
function invoked within a :func:`trio.run` calls
:func:`asyncio.sleep`, or a function invoked within an
:func:`asyncio.run` calls :func:`trio.sleep`, the sleep function will
send a message to the event loop that the event loop doesn't know how
to handle, and some sort of error will result.

In a program that uses trio-asyncio, you probably have some async
functions implemented in terms of Trio calls and some implemented in
terms of asyncio calls. In order to keep track of which is which,
we'll call these "Trio-flavored" and "asyncio-flavored" functions,
respectively.  It is critical that you understand which functions in
your program are Trio-flavored and which are asyncio-flavored, just
like it's critical that you understand which functions are synchronous
and which ones are async. Unfortunately, there's no syntactic marker
for flavor: both Trio-flavored and asyncio-flavored functions are
defined with ``async def fn()`` and call other async functions with
``await other_fn()``.  You'll have to keep track of it some other
way. To help you out, every function in trio-asyncio documents its
flavor, and we recommend that you follow this convention in your own
programs too.

The general rules that determine flavor are as follows:

* Every async function in the ``trio`` module is Trio-flavored.
  Every async function in the ``asyncio`` module is asyncio-flavored.

* Flavor is transitive: if async function ``foo()`` calls ``await
  bar()``, then ``foo()`` has ``bar()``'s flavor. (If ``foo()``
  calls ``await baz()`` too, then ``bar()`` and ``baz()`` had better
  have the same flavor.)

* trio-asyncio gives you the ability to call functions whose flavor is
  different than your own, but you must be explicit about it.
  :func:`trio_asyncio.aio_as_trio` takes an asyncio-flavored function
  and returns a Trio-flavored wrapper for it;
  :func:`trio_as_aio` takes a Trio-flavored function and
  returns an asyncio-flavored wrapper for it.

If you don't keep track of your function flavors correctly, you might
get exceptions like the following:

* If you call a Trio function where an asyncio function is expected: ``RuntimeError:
  Task got bad yield:`` followed by either ``WaitTaskRescheduled(abort_func=...)``
  or ``<class 'trio._core._traps.CancelShieldedCheckpoint'>``

* If you call an asyncio function where a Trio function is expected: ``TypeError:
  trio.run received unrecognized yield message <Future ...>.``

Other errors are possible too.

-----------------------
 Flavor versus context
-----------------------

The concept of function flavor is distinct from the concept of
"asyncio context" or "Trio context". You're in Trio context if you're
(indirectly) inside a call to :func:`trio.run`. You're in asyncio
context if :func:`asyncio.get_running_loop` returns a valid event
loop. In a trio-asyncio program, you will frequently be in both Trio
context and asyncio context at the same time, but each async function is
either Trio-flavored or asyncio-flavored (not both).

Most *synchronous* asyncio or Trio functions (:meth:`trio.Event.set`,
:meth:`asyncio.StreamWriter.close`, etc) only require you to be in
asyncio or Trio context, and work equally well regardless of the
flavor of function calling them. The exceptions are functions that
access the current task (:func:`asyncio.current_task`,
:func:`trio.hazmat.current_task`, and anything that calls them),
because there's only a meaningful concept of the current *foo* task
when a *foo*-flavored function is executing.  For example, this means
context managers that set a timeout on their body (``with
async_timeout.timeout(N):``, ``with trio.move_on_after(N):``) must be
run from within the correct flavor of function.

---------------------------------
 Flavor transitions are explicit
---------------------------------

As mentioned above, trio-asyncio does not generally allow you to
transparently call ``await trio.something()`` from asyncio code, nor
vice versa; you need to use :func:`aio_as_trio` or
:func:`trio_as_aio` when calling a function whose flavor is
different than yours. This is certainly more frustrating than having
it "just work". Unfortunately, semantic differences between Trio and
asyncio (such as how to signal cancellation) need to be resolved at
each boundary between asyncio and Trio, and we haven't found a way to
do this with acceptable performance and robustness unless those
boundaries are marked.

If you insist on living on the wild side, trio-asyncio does provide
:func:`allow_asyncio` which allows *limited,
experimental, and slow* mixing of Trio-flavored and asyncio-flavored
calls in the same Trio-flavored function.

-------------------------------------------
 trio-asyncio's place in the asyncio stack
-------------------------------------------

At its base, asyncio doesn't know anything about futures or
coroutines, nor does it have any concept of a task. All of these
features are built on top of the simpler interfaces provided by the
event loop. The event loop itself has little functionality beyond executing
synchronous functions submitted with :meth:`~asyncio.loop.call_soon`
and :meth:`~asyncio.loop.call_later`
and invoking I/O availability callbacks registered using
:meth:`~asyncio.loop.add_reader` and :meth:`~asyncio.loop.add_writer`
at the appropriate times.

trio-asyncio provides an asyncio event loop implementation which
performs these basic operations using Trio APIs. Everything else in
asyncio (futures, tasks, cancellation, and so on) is ultimately
implemented in terms of calls to event loop methods, and thus works
"magically" with Trio once the trio-asyncio event loop is
installed. This strategy provides a high level of compatibility with
asyncio libraries, but it also means that asyncio-flavored code
running under trio-asyncio doesn't benefit much from Trio's more
structured approach to concurrent programming: cancellation,
causality, and exception propagation in asyncio-flavored code are just
as error-prone under trio-asyncio as they are under the default
asyncio event loop. (Of course, your Trio-flavored code will still
benefit from all the usual Trio guarantees.)

If you look at a Trio task tree, you'll see only one Trio task for the
entire asyncio event loop. The distinctions between different asyncio
tasks are erased, because they've all been merged into a single pot of
callback soup by the time they get to trio-asyncio. Similarly, context
variables will only work properly in asyncio-flavored code when
running Python 3.7 or later (where they're supported natively), even
though Trio supports them on earlier Pythons using a backport package.

----------------------------
 Event loop implementations
----------------------------

An asyncio event loop may generally be interrupted and restarted at any
time, simply by making repeated calls to :meth:`run_until_complete()
<asyncio.loop.run_until_complete>`.
Trio, however, requires one long-running main loop. trio-asyncio bridges
this gap by providing two event loop implementations.

* The preferred option is to use an "async loop": inside a
  Trio-flavored async function, write ``async with
  trio_asyncio.open_loop() as loop:``.  Within the ``async with``
  block (and anything it calls, and any tasks it starts, and so on),
  :func:`asyncio.get_event_loop` and :func:`asyncio.get_running_loop`
  will return *loop*. You can't manually start and stop an async
  loop. Instead, it starts when you enter the ``async with`` block and
  stops when you exit the block.

* The other option is a "sync loop".
  If you've imported trio-asyncio but aren't in Trio context, and you haven't
  installed a custom event loop policy, calling :func:`asyncio.new_event_loop`
  (including the implicit call made by the first :func:`asyncio.get_event_loop`
  in the main thread) will give you an event loop that transparently runs
  in a separate thread in order to support multiple
  calls to :meth:`~asyncio.loop.run_until_complete`,
  :meth:`~asyncio.loop.run_forever`, and :meth:`~asyncio.loop.stop`.
  Sync loops are intended to allow trio-asyncio to run the existing
  test suites of large asyncio libraries, which often call
  :meth:`~asyncio.loop.run_until_complete` on the same loop multiple times.
  Using them for other purposes is deprecated.
