
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
	"""A selector that hooks into a TrioEventLoop."""
	def __init__(self, loop):
		super().__init__()
#		self._loop = loop
#	
#	def close(self):
#		self._loop = None
#		super().close()
#
#	def register(self, fileobj, events, data=None):
#		assert data
#		key = super().register(fileobj, events, data)
#		if key.events & EVENT_READ:
#			self._loop._add_read_handle(key.fd, data[0])
#		if key.events & EVENT_WRITE:
#			self._loop._add_write_handle(key.fd, data[1])
#		return key
#
#	def unregister(self, fileobj):
#		key = super().unregister(fileobj, events, data)
#		if key.events & EVENT_READ:
#			self._loop._remove_read_handle(key.fd)
#		if key.events & EVENT_WRITE:
#			self._loop._remove_write_handle(key.fd)
#		return key
#
#	def modify(self, fileobj, events, data=None):
#		okey = self.unregister(fileobj)
#		key = self.register(fileobj, events, data)
#		return key
#		
	def select(self, timeout=None):
		raise NotImplementedError
	def _select(self, r,w,x, timeout=None):
		raise NotImplementedError
	
class TrioEventLoop(asyncio.unix_events._UnixSelectorEventLoop):
	"""An asyncio mainloop for trio

	This code implements a semi-efficient way to run asyncio code within Trio.
	"""
	_saved_fds = None

	def __init__(self):
		self._q = trio.Queue(9999)

		super().__init__(_TrioSelector(self))

		# now kill things we supersede
		self._ready = _AddHandle(self)
		self._scheduled = _Clear()
		self._laters = {}
		del self._clock_resolution
		del self._current_handle
		del self._coroutine_wrapper_set

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
			mask, (writer, writer) = key.events, key.data
			self._selector.modify(fd, mask | EVENT_READ, (handle, writer))
			return writer

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

	# writers
	# s/read/writ/g

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

	# mainloop

	async def _run_forever(self):
		try:
			async with trio.open_nursery() as nursery:
				self._nursery = nursery
				self._stopping = False
				await self._restore_fds()

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
					self._save_fds()
					del self._nursery
					self._stopping = True

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
