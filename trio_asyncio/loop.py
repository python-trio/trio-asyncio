
# This code implements a clone of the asyncio mainloop which hooks into
# Trio.

import trio
import asyncio
import logging
logger = logging.getLogger(__name__)

from functools import partial

class _Clear:
	def clear(self):
		pass

_tag = 1
def _next_tag():
	global _tag
	_tag += 1
	return _tag
	
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
		self._ready = _Clear()
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

	def call_later(self, delay, callback, *args):
		assert delay >= 0, delay
		tag = _next_tag()
		self._q.put_nowait((self.__call_later,(tag,delay,callback,)+args,{},True))

		class CancelLater:
			def __init__(_self, tag):
				_self.tag = tag
			def cancel(_self):
				later = self._laters.get(_self.tag,None)
				if later is not None:
					later.cancel()
		return CancelLater(tag)

	def call_trio(self, p,*a,**k):
		"""Call an asynchronous Trio-ish function from asyncio.

		Returns a Future with the result / exception.
		"""
		f = asyncio.Future(loop=self)
		self._q.put_nowait((self.__call_trio,(f,p,)+a,k,True))
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
		self._q.put_nowait((self.__call_trio_sync,(f,p,)+a,k,True))
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

	async def __call_later(self, tag, delay, callback, *args):
		try:
			with trio.open_cancel_scope() as scope:
				self._laters[tag] = scope
				await trio.sleep(delay)
		finally:
			del self._laters[tag]
		callback(*args)

	def call_at(self, when, callback, *args):
		raise NotImplementedError

	def call_soon(self, callback, *args):
		self._q.put_nowait((callback,args,{},False))
	def call_soon_async(self, callback, *args):
		self._q.put_nowait((callback,args,{},True))

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
				self._event = trio.Event()
				try:
					async for obj in self._q:
						if obj is None:
							break
						p,a,k,is_async = obj
						if is_async:
							nursery.start_soon(partial(p,*a,**k))
						else:
							try:
								p(*a,**k)
							except Exception as exc:
								logger.exception("Calling %s %s %s:", p,a,k)
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
