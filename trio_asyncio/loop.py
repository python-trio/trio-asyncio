
# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import trio
import asyncio
import logging
logger = logging.getLogger(__name__)

from functools import partial
from asyncio.events import _format_callback, _get_function_source

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
		
class TrioEventLoop(asyncio.unix_events._UnixSelectorEventLoop):
	"""An asyncio mainloop for trio

	This code implements a semi-efficient way to run asyncio code within Trio.
	"""
	def __init__(self):
		self._q = trio.Queue(9999)
		self._saved_readers = {}
		self._saved_writers = {}

		super().__init__()

		# now kill things we supersede
		self._ready = _AddHandle(self)
		self._scheduled = _Clear()
		self._laters = {}
		del self._clock_resolution
		del self._current_handle
		del self._coroutine_wrapper_set

		self._readers = {}
		self._writers = {}

	# easy methods to supersede
	def time(self):
		return trio.current_time()

	def call_trio(self, p,*a,**k):
		"""Call an asynchronous Trio-ish function from asyncio.

		Returns a Future with the result / exception.
		"""
		f = asyncio.Future(loop=self)
		h = Handle(self.__call_trio,(f,p,)+a,k,self,False)
		self._q.put_nowait(h)
		return f

	async def __call_trio(self, f,p,*a,**k):
		try:
			res = await p(*a,**k)
		except trio.Cancelled:
			f.cancel()
		except BaseException as exc:
			f.set_exception(exc)
		else:
			f.set_result(res)

	def call_trio_sync(self, p,*a,**k):
		"""Call a synchronous Trio-requiring function from asyncio.

		Returns a Future with the result / exception.
		"""
		f = asyncio.Future(loop=self)
		h = Handle(self.__call_trio_sync,(f,p,)+a,k,self,False)
		self._q.put_nowait(h)
		return f

	async def __call_trio_sync(self, f,p,*a,**k):
		try:
			res = p(*a,**k)
		except trio.Cancelled:
			f.cancel()
		except BaseException as exc:
			f.set_exception(exc)
		else:
			f.set_result(res)

	def call_later(self, delay, callback, *args):
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
		raise NotImplementedError

	def call_soon(self, callback, *args):
		h = Handle(callback, args, {}, self, True)
		self._q.put_nowait(h)

	def call_soon_async(self, callback, *args):
		h = Handle(callback, args, {}, self, False)
		self._q.put_nowait(h)

	def _add_callback(self, handle):
		raise NotImplementedError
	def _add_callback_signalsafe(self, handle):
		raise NotImplementedError
	def _timer_handle_cancelled(self, handle):
		raise NotImplementedError
	def _run_once(self):
		raise NotImplementedError
	def add_signal_handler(self, sig, callback, *args):
		raise NotImplementedError
	def remove_signal_handler(self, sig):
		raise NotImplementedError

	# readers

	def add_reader(self, fd, callback, *args):
		if hasattr(fd,'fileno'):
			fd = fd.fileno()
		self._saved_readers[fd] = (callback,args)
		self.call_soon(self.__add_reader, fd, callback, *args)
	_add_reader = add_reader
	def __add_reader(self, fd, callback, *args):
		self._nursery.start_soon(self._reader_loop, fd, callback, *args)
	async def _reader_loop(self, fd, callback, *args, task_status=trio.STATUS_IGNORED):
		task_status.started()
		with trio.open_cancel_scope() as scope:
			self._readers[fd] = scope
			try:
				while fd in self._saved_readers:
					await trio.hazmat.wait_readable(fd)
					callback(*args)
			finally:
				del self._readers[fd]
	def remove_reader(self, fd):
		if hasattr(fd,'fileno'):
			fd = fd.fileno()
		try:
			del self._saved_readers[fd]
		except KeyError:
			return False
		self.call_soon(self.__remove_reader, fd)
		return True
	_remove_reader = remove_reader
	def __remove_reader(self, fd):
		reader = self._readers.get(fd,None)
		if reader is not None:
			reader.cancel()
	def _start_readers(self):
		for k,v in self._saved_readers.items():
			callback,args = v
			self.add_reader(k, callback,*args)

	# writers
	# s/read/writ/g

	def add_writer(self, fd, callback, *args):
		if hasattr(fd,'fileno'):
			fd = fd.fileno()
		self._saved_writers[fd] = (callback,args)
		self.call_soon(self.__add_writer, fd, callback, *args)
	_add_writer = add_writer
	def __add_writer(self, fd, callback, *args):
		self._nursery.start_soon(self._writer_loop, fd, callback, *args)
	async def _writer_loop(self, fd, callback, *args, task_status=trio.STATUS_IGNORED):
		task_status.started()
		with trio.open_cancel_scope() as scope:
			self._writers[fd] = scope
			try:
				while fd in self._saved_writers:
					await trio.hazmat.wait_writable(fd)
					callback(*args)
			finally:
				del self._writers[fd]
	def remove_writer(self, fd):
		if hasattr(fd,'fileno'):
			fd = fd.fileno()
		try:
			del self._saved_writers[fd]
		except KeyError:
			return False
		self.call_soon(self.__remove_writer, fd)
		return True
	_remove_writer = remove_writer
	def __remove_writer(self, fd):
		writer = self._writers.get(fd,None)
		if writer is not None:
			writer.cancel()
	def _start_writers(self):
		for k,v in self._saved_writers.items():
			callback,args = v
			self.add_writer(k, callback,*args)

	def default_exception_handler(self, context):
		import sys,pprint
		pprint.pprint(context, stream=sys.stderr)

	# mainloop

	async def _run_forever(self):
		try:
			async with trio.open_nursery() as nursery:
				self._nursery = nursery
				self._stopping = False
				try:
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
					del self._nursery
					self._stopping = True
					for j in self._readers.values():
						j.cancel()

			# for next time
			self._start_readers()
			self._start_writers()
		except BaseException as exc:
			print(*trio.format_exception(type(exc),exc,exc.__traceback__))

	def run_forever(self):
		trio.run(self._run_forever)
		
	#trio
	async def _stop(self):
		"""Stop this event loop.
		"""
		self._running = False

	def stop(self):
		self._q.put_nowait(None)
		
class TrioPolicy(asyncio.unix_events._UnixDefaultEventLoopPolicy):
	_loop_factory = TrioEventLoop

asyncio.set_event_loop_policy(TrioPolicy())
