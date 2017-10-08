==============
 trio-asyncio
==============

`trio-asyncio` is a re-implementation of the `asyncio` mainloop on top of
Trio.

+++++++++++
 Rationale
+++++++++++

There are quite a few asyncio-compatible libraries. Trio, not so much.

On the other hand, Trio has native concepts of tasks and task cancellation.
Asyncio, on the other hand, is based on chaining Future objects, albeit
with nicer syntax.

Thus, Trio should be able to use asyncio libraries.

+++++++
 Usage
+++++++

Importing ``trio_asyncio`` replaces the default ``asyncio`` event loop with
``trio_asyncio``'s version. Thus it's mandatory to do that import as soon
as possible.

----------------------
 Startup and shutdown
----------------------

Trio main loop
++++++++++++++

Typically, you start with a Trio program which you need to extend with
asyncio code.

* before:

	import trio
    trio.run(your_code, \*args)


* after:

	import trio_asyncio
	import asyncio

	loop = asyncio.get_event_loop()
    loop.run_task(your_code, \*args)


Within ``your_code``, the asyncio mainloop is active. It will be stopped
automatically when that procedure exits.

Asyncio main loop
+++++++++++++++++

Alternately, you may start with an asyncio mainloop.

Starting up
-----------

This is the easy part:

	import trio_asyncio
	import asyncio

	loop = asyncio.get_event_loop()
    loop.run_until_complete(your_code())

I.e. your code does not change at all, other than importing trio_asyncio.

Interrupting the loop
---------------------

You might have been doing something like this:

	loop.run_until_complete(startup_code())
	loop.run_until_complete(main_code())
	loop.run_until_complete(cleanup_code())

The Trio event loop that runs ``trio_asyncio`` is restarted between these
calls. While that is supported, it's generally not advisable.

Instead, you should use a single async main function:

	async def main_code():
		try:
			await startup_code()
			await main_code()
		finally:
			await cleanup_code()
	loop.run_until_complete(main_code())

Stopping
--------

As usual, i.e. by calling ``loop.stop()`` within the loop (or by exiting ``main_code``).

---------------
 Cross-calling
---------------

Calling Trio from asyncio
+++++++++++++++++++++++++

Pass the function and any arguments to ``loop.call_trio()``. This method
returns a standard asyncio Future which you can await, add callbacks to,
or whatever.

Both unnamed and keyword arguments are supported.

	async def some_trio_code(foo):
		await trio.sleep(1)
		return foo*2
	
	future = loop.call_trio(some_trio_code, 21)
	res = await future
	assert res == 42

If the function is not asyncronous but still needs to run within the Trio
main loop for some reason (for instance, it might call ``trio.time()``),
use ``loop.call_trio_sync()``. This also returns a Future.

	def some_trio_code(foo):
		return foo*2
	
	future = loop.call_trio(some_trio_code, 21)
	res = await future
	assert res == 42

Calling asyncio from Trio
+++++++++++++++++++++++++

Pass the function and any arguments to ``loop.call_asyncio()``. This method
conforms to Trio's standard task semantics.

Both unnamed and keyword arguments are supported.

	async def some_asyncio_code(foo):
		await asyncio.sleep(1, loop=loop)
		return foo*20
	
	res = await loop.call_asyncio(some_trio_code, 21, _scope=…)
	assert res == 420

If you already have a future you need to await, call ``loop.wait_for()``:

	async def some_asyncio_code(foo):
		await asyncio.sleep(1, loop=loop)
		return foo*20
	
	fut = asyncio.ensure_future(some_asyncio_code(21), loop=loop)
	res = await loop.wait_for(fut, _scope=…)
	assert res == 420

You'll notice the ``_scope`` argument. This is a Trio cancellation scope.
If you don't pass one in, the inner-most scope of the current task will be
used. This may or may not be what you want.

Errors and cancellations
++++++++++++++++++++++++

Errors and cancellations are propagated transparently.

For errors, this is straightforward.

Cancellations are also propagated whenever possible. This means

* the code called from ``call_trio()`` is cancelled when you cancel
  the future it returns

* when the code called from ``call_trio()`` is cancelled, 
  the future it returns gets cancelled

* the future used in ``wait_for()`` is cancelled when the Trio code
  calling it is stopped

* the Trio code calling ``wait_for()`` is cancelled when the future
  is cancelled, or when its exception is set to an instance of
  ``asyncio.CancelledError``

----------------
 Deferred Calls
----------------

``loop.call_soon()`` and friends work as usual.

There is one caveat: ``loop.time()`` is implemented in terms of
``trio.time()`` which does not survive restarting the loop. Timeouts
which are queued within the loop will survive a restart, but absolute
timeouts (``loop.call_at()``) stored in your code will not survive and are
likely to run (much) too early.

Fortunately, such usage is rare.

---------
 Threads
---------

``loop.run_in_executor()`` works as usual.

There is one caveat: the executor must be either ``None`` or an instance of
``trio_asyncio.TrioExecutor``. The constructor of this class accepts one
argument: the number of workers.

------------------
 File descriptors
------------------

``add_reader`` and ``add_writer`` work as usual, if you really need them.

However, you might consider converting these calls to native Trio tasks.

---------
 Signals
---------

``add_signal_handler`` works as usual.

------------
 Extensions
------------

All calls which accept a function and a number of plain arguments also accept
keyword arguments.

++++++++++++++++++++++
 Hacking trio-asyncio
++++++++++++++++++++++

-----------
 Licensing
-----------

Like trio, trio-asyncio is licensed under both the MIT and Apache licenses.
Submitting patches or pull requests imply your acceptance of these licenses.

---------
 Patches
---------

are accepted gladly.

---------
 Testing
---------

As in trio, testing is done with ``pytest``. Tests include the complete
Python 3.6 asyncio test suite.

Test coverage is close to 100%. Please keep it that way.

++++++++
 Author
++++++++

Matthias Urlichs <matthias@urlichs.de>

