import socket
import threading
import time

import asyncio as _asyncio
socketpair = socket.socketpair


class TestConfig:
    def __init__(self):
        # Stop on first fail or error
        self.fail_fast = False

        # Run tests forever to catch sporadic errors
        self.forever = False

        # Verbosity 0..4: 0=less messages (CRITICAL), 4=more messages (DEBUG)
        self.verbosity = 0

        # List of test names to include, empty list means that all tests
        # are included
        self.includes = []

        # List of test names to exclude, empty list means that no test is
        # excluded
        self.excludes = []

        # modules
        self.asyncio = _asyncio
        self.socket = socket
        self.threading = threading

        # functions
        self.socketpair = socketpair
        self.sleep = time.sleep

        # features of the implementations

        # The event loop can be run in a thread different than the main thread?
        self.support_threads = True

        # http://bugs.python.org/issue22922
        # call_soon() now raises an exception when the event loop is closed
        self.call_soon_check_closed = True

        # http://bugs.python.org/issue25593
        # Change semantics of EventLoop.stop(). Replace _StopError exception
        # with a new stopping attribute.
        self.stopping = True

    def prepare(self, testcase):
        # import pdb;pdb.set_trace()
        # policy = self.new_event_pool_policy()
        # self.asyncio.set_event_loop_policy(policy)
        testcase.addCleanup(self.asyncio.set_event_loop_policy, None)

        testcase.loop = self.asyncio.get_event_loop()
        # testcase.addCleanup(testcase.loop.close)
        # testcase.addCleanup(self.asyncio.set_event_loop, None)


class TestCase:
    pass


#    @classmethod
#    def setUpClass(cls):
#        cls.config = config
#
#    def setUp(self):
#        self.config.prepare(self)
