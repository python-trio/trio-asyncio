+++++++++++
 Rationale
+++++++++++

Trio has native concepts of tasks and task cancellation. Asyncio is based
on callbacks and chaining Futures, albeit with nicer syntax, which make
handling of failures and timeouts fundamentally less reliable, esp. in
larger programs. Thus, you *really* want to use trio in your project.
 
On the other hand, there are quite a few asyncio-enhanced libraries. You
*really* don't want to re-invent any wheels in your project.

Thus, being able to use asyncio libraries from Trio is useful.
Trio-Asyncio enables you to do that, and more.

--------------------------------------
 Transparent vs. explicit translation
--------------------------------------

Trio-Asyncio does not try to magically allow you to call ``await
trio_code()`` from asyncio, nor vice versa. There are multiple reasons for
this, among them

* "Explicit is better than implicit" is one of Python's core design guidelines.

* Semantic differences need to be resolved at the asyncio>trio and trio>asyncio 
  boundary. However, there is no good way to automatically find these
  boundaries, much less insert code into them.

* Even worse, a trio>asyncio>trio transition, or vice versa, would be
  invisible without traversing the call chain at every non-trivial event;
  that would impact performance unacceptably.

Therefore, an attempt to execute such a cross-domain call will result in an
irrecoverable error. You need to keep your code's ``asyncio`` and ``trio``
domains rigidly separate.

++++++++++++++++++++++++
 Principle of operation
++++++++++++++++++++++++

The core of the "normal" asyncio main loop is the repeated execution of
synchronous code that's submitted to
:meth:`python:asyncio.loop.call_soon` or
:meth:`python:asyncio.loop.call_later`, or as the callbacks for
:meth:`python:asyncio.loop.add_reader` /
:meth:`python:asyncio.loop.add_writer`.

Everything else within the ``asyncio`` core, esp. Futures, Coroutines, and
``await``'ing them, is just syntactic sugar. There is no concept of a
task; while a Future can be cancelled, that in itself doesn't affect the
code responsible for fulfilling it.

Thus, the core of trio-asyncio is a class which implements these methods,
and a task that processes them within (its own version of) the asyncio main
loop. It also supplants another few of the standard loop's key functions.

This works rather well: trio-asyncio has passed the complete Python 3.6
asyncio test suite.

An asyncio main loop may be interrupted and restarted at any
time, simply by repeated calls to ``loop.run_until_complete()``.
Trio, however requires one long-running main loop. These differences are 
bridged by a loop implementation which moves trio operations to a separate
thread. A synchronous lock ensures that there are no concurrency issues.

