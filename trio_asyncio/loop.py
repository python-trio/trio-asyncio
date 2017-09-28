
# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import sys
import trio
import asyncio
import logging
logger = logging.getLogger(__name__)

from functools import partial
from asyncio.events import _format_callback, _get_function_source
from selectors import _BaseSelectorImpl, EVENT_READ, EVENT_WRITE

class _Clear:
	def clear(self):
		pass

class _AddHandle(_Clear):
	__slots__ = ('_loop',)
	def __init__(self, loop):
		self._loop = loop
	
	def append(self, handle):
		assert self._loop == handle._loop
		handle._loop._q.put_nowait(handle)

_tag = 1
def _next_tag():
	global _tag
	_tag += 1
	return _tag
	
def _format_callback_source(func, args, kwargs):
	func_repr = _format_callback(func, args, kwargs)
	source = _get_function_source(func)
	if source:
		func_repr += ' at %s:%s' % source
	return func_repr

class Handle(asyncio.Handle):
	"""
	This extends asyncio.Handle with a way to pass keyword argument.
	
	Also, ``is_sync`` declares whether ``callback`` is synchronous.
	As a special case, if its value is ``None`` the callback will
	be called with the handle as its sole argument.
	"""
	__slots__ = ('_kwargs', '_is_sync', '_scope')

	def __init__(self, callback, args, kwargs, loop, is_sync):
		super().__init__(callback, args, loop)
		self._kwargs = kwargs
		self._is_sync = is_sync
		self._scope = None

	def cancel(self):
		super().cancel()
		self._kwargs = None
		if self._scope is not None:
			self._scope.cancel()

	def _cb_future_cancel(self, f):
		"""If a Trio task completes an asyncio Future,
		add this callback to the future
		and set ``_scope`` to the Trio cancel scope
		so that the task is terminated when the future gets canceled.

		"""
		if f.cancelled():
			self.cancel()

	def _repr_info(self):
		info = [self.__class__.__name__]
		if self._cancelled:
			info.append('cancelled')
		if self._callback is not None:
			info.append(_format_callback_source(self._callback, self._args, self._kwargs))
		if self._source_traceback:
			frame = self._source_traceback[-1]
			info.append('created at %s:%s' % (frame[0], frame[1]))
		return info

	def _call_sync(self):
		assert self._is_sync
		assert not self._cancelled
		return self._callback(*self._args, **self._kwargs)
		
	async def _call_async(self):
		assert not self._is_sync
		assert not self._cancelled
		try:
			with trio.open_cancel_scope() as scope:
				self._scope = scope
				if self._is_sync is None:
					res = await self._callback(self)
				else:
					res = await self._callback(*self._args, **self._kwargs)
		finally:
			self._scope = None
		return res
		
class _TrioSelector(_BaseSelectorImpl):
	"""A selector that hooks into a ``TrioEventLoop``.

	In fact it's just a basic selector that disables the actual
	``select()`` method, as that is controlled by the event loop.
	"""
	def select(self, timeout=None):
		raise NotImplementedError
	def _select(self, r,w,x, timeout=None):
		raise NotImplementedError
	
class TrioEventLoop(asyncio.unix_events._UnixSelectorEventLoop):
	"""An asyncio mainloop for trio

	This code implements a semi-efficient way to run asyncio code within Trio.
	"""
	_saved_fds = None
	_token = None

	def __init__(self):
		# Processing queue
		self._q = trio.Queue(9999)

		# interim storage for calls to ``call_soon_threadsafe``
		# while the main loop is not running
		self._delayed_calls = []

		super().__init__(_TrioSelector())

		# replaced internal data
		self._ready = _AddHandle(self)
		self._scheduled = _Clear()

		# internals disabled by default
		del self._clock_resolution
		del self._current_handle
		del self._coroutine_wrapper_set

	def time(self):
		"""Trio's idea of the current time.

		Unlike asyncio.loop's version, this function may only be called
		while the loop is running.
		"""
		return trio.current_time()

	def call_trio(self, p,*a,**k):
		"""Call an asynchronous Trio-ish function from asyncio.

		Returns a Future with the result / exception.

		Cancelling the future will cancel the task running your procedure,
		or prevent it from starting if that is stil possible.
		"""
		f = asyncio.Future(loop=self)
		h = Handle(self.__call_trio,(f,p,)+a,k,self,None)
		if self._token is None:
			self._delayed_calls.append(Handle(self._q.put_nowait,(h,),{},self,False))
		else:
			self._q.put_nowait(h)
		f.add_done_callback(h._cb_future_cancel)
		return f

	async def __call_trio(self, h):
		f, proc, *args = h._args
		if f.cancelled():
			return
		try:
			with trio.open_cancel_scope() as scope:
				h._scope = scope
				res = await proc(*args,**h._kwargs)
		except trio.Cancelled:
			f.cancel()
		except BaseException as exc:
			f.set_exception(exc)
		else:
			f.set_result(res)

	def call_trio_sync(self, p,*a,**k):
		"""Call a synchronous function from asyncio.

		Returns a Future with the result / exception.

		Cancelling the future will prevent the code from running,
		assuming that is still possible.

		You might need to use this method if your code needs access to
		features which are only available when Trio is running, such as
		global task-sepcific variables or the current time.
		Otherwise, simply call the code in question directly.
		"""
		f = asyncio.Future(loop=self)
		if self._token is None:
			h = Handle(self.__call_trio_sync,(f,p,)+a,k,self,None)
			self._delayed_calls.append(h)
		else:
			h = Handle(p,a,k,self,False)
			self._q.put_nowait(h)
		return f

	async def __call_trio_sync(self, h):
		f, proc, *args = h._args
		if f.cancelled():
			return
		try:
			res = proc(*args,**h._kwargs)
		except trio.Cancelled: # should probably never happen, but …
			f.cancel()
		except BaseException as exc:
			f.set_exception(exc)
		else:
			f.set_result(res)

	def call_later(self, delay, callback, *args):
		"""asyncio's timer-based delay
		"""
		assert delay >= 0, delay
		tag = _next_tag()
		h = Handle(self.__call_later, (delay,callback)+args, {}, self, None)
		self._q.put_nowait(h)
		return h

	async def __call_later(self, h):
		delay = h._args[0]
		callback = h._args[1]
		args = h._args[2:]
		await trio.sleep(delay)
		if not h._cancelled:
			callback(*args, **h._kwargs)

	def call_at(self, when, callback, *args):
		return call_later(when - self.time(), callback, *args)

	def call_soon(self, callback, *args):
		h = Handle(callback, args, {}, self, True)
		self._q.put_nowait(h)

	def call_soon_threadsafe(self, callback, *args):
		h = Handle(callback, args, {}, self, True)
		if self._token is None:
			self._delayed_calls.append(h)
		else:
			self._token.run_sync_soon(self._q.put_nowait,h)
		return h
		
	def call_soon_async(self, callback, *args):
		h = Handle(callback, args, {}, self, False)
		self._q.put_nowait(h)

	# supersede some built-ins which should not be used

	def _add_callback(self, handle):
		raise NotImplementedError
	def _add_callback_signalsafe(self, handle):
		raise NotImplementedError
	def _timer_handle_cancelled(self, handle):
		raise NotImplementedError
	def _run_once(self):
		raise NotImplementedError

	# TODO

	def add_signal_handler(self, sig, callback, *args):
		raise NotImplementedError
	def remove_signal_handler(self, sig):
		raise NotImplementedError

	# reading from a file descriptor

	def _add_reader(self, fd, callback, *args):
		self._check_closed()
		handle = Handle(callback, args, {}, self, True)
		reader = self._set_read_handle(fd, handle)
		if reader is not None:
			reader.cancel()
		self.call_soon(self.__add_reader, fd, handle)

	def _set_read_handle(self, fd, handle):
		try:
			key = self._selector.get_key(fd)
		except KeyError:
			self._selector.register(fd, EVENT_READ, (handle, None))
			return None
		else:
			mask, (reader, writer) = key.events, key.data
			self._selector.modify(fd, mask | EVENT_READ, (handle, writer))
			return reader

	def __add_reader(self, fd, handle):
		self._nursery.start_soon(self._reader_loop, fd, handle)

	async def _reader_loop(self, fd, handle, task_status=trio.STATUS_IGNORED):
		task_status.started()
		with trio.open_cancel_scope() as scope:
			handle._scope = scope
			try:
				while not handle._cancelled:
					await trio.hazmat.wait_readable(fd)
					handle._call_sync()
			except Exception as exc:
				logger.exception("Reading %d: Calling %s", fd, handle)
			finally:
				handle._scope = None

	# writing to a file descriptor

	def _add_writer(self, fd, callback, *args):
		self._check_closed()
		handle = Handle(callback, args, {}, self, True)
		writer = self._set_write_handle(fd, handle)
		if writer is not None:
			writer.cancel()
		self.call_soon(self.__add_writer, fd, handle)

	def _set_write_handle(self, fd, handle):
		try:
			key = self._selector.get_key(fd)
		except KeyError:
			self._selector.register(fd, EVENT_WRITE, (None, handle))
		else:
			mask, (reader, writer) = key.events, key.data
			self._selector.modify(fd, mask | EVENT_WRITE, (reader, handle))
			return writer

	def __add_writer(self, fd, handle):
		self._nursery.start_soon(self._writer_loop, fd, handle)

	async def _writer_loop(self, fd, handle, task_status=trio.STATUS_IGNORED):
		task_status.started()
		with trio.open_cancel_scope() as scope:
			handle._scope = scope
			try:
				while not handle._cancelled:
					await trio.hazmat.wait_writable(fd)
					handle._call_sync()
			except Exception as exc:
				logger.exception("writing %d: Calling %s %s", fd, callback, args)
			finally:
				handle._scope = None

	def _save_fds(self):
		map = self._selector.get_map()
		saved = [{},{}]
		for fd,key in list(self._selector.get_map().items()):
			for flag in (0,1):
				if key.events & (1<<flag):
					handle = key.data[flag]
					assert handle is not None
					if not handle._cancelled:
						if handle._scope is not None:
							handle._scope.cancel()
						saved[flag][fd] = handle

		self._saved_fds = saved
		self._selector = _TrioSelector()

	async def _restore_fds(self):
		if not self._saved_fds:
			return
		for flag,fds in enumerate(self._saved_fds):
			for fd,handle in fds.items():
				if handle._cancelled:
					continue
				if flag:
					old = self._set_write_handle(fd, handle)
					self._nursery.start_soon(self._writer_loop, fd, handle)
				else:
					old = self._set_read_handle(fd, handle)
					self._nursery.start_soon(self._reader_loop, fd, handle)
				assert old is None
		self._saved_fds = []

	def default_exception_handler(self, context):
		import sys,pprint
		pprint.pprint(context, stream=sys.stderr)

	# Trio-based main loop

	async def main_loop(self, task_status=trio.STATUS_IGNORED):
		"""This is the Trio replacement of the asyncio loop's main loop.

		Run this method as a standard Trio thread if your main code is
		Trio-based and you need to call asyncio code.

		Use ``run_forever()`` or ``run_until_complete()`` instead if your
		main code is asyncio-based.
		"""
		task_status.started()
		try:
			async with trio.open_nursery() as nursery:
				self._nursery = nursery
				self._stopping = False
				self._token = trio.hazmat.current_trio_token()
				await self._restore_fds()

				try:
					for obj in self._delayed_calls:
						if not obj._cancelled:
							obj._call_sync()
					self._delayed_calls = []
					async for obj in self._q:
						if obj is None:
							break
						if obj._cancelled:
							continue

						if getattr(obj, '_is_sync', True) is True:
							try:
								obj._callback(*obj._args, **getattr(obj, '_kwargs', {}))
							except Exception as exc:
								logger.exception("Calling %s:", repr(obj))
						else:
							nursery.start_soon(obj._call_async)
				finally:
					self._save_fds()
					del self._nursery
					self._stopping = True
					self._token = None

		except BaseException as exc:
			print(*trio.format_exception(type(exc),exc,exc.__traceback__))

	def run_forever(self):
		"""Start the main loop

		This method simply runs ``.main_loop()`` as a trio-enabled version
		of the asyncio main loop.

		Use this (usually via ``run_until_complete()``) if your code
		is asyncio-based and you want to use some trio features or
		libraries.

		Use ``main_loop()`` instead if you main code is trio-based.
		"""
		trio.run(self.main_loop)
		
	def stop(self):
		self._q.put_nowait(None)
		
class TrioPolicy(asyncio.unix_events._UnixDefaultEventLoopPolicy):
	_loop_factory = TrioEventLoop

asyncio.set_event_loop_policy(TrioPolicy())
