from __future__ import absolute_import
from tests.aiotest import socketpair
from tests import aiotest

class AddReaderTests(aiotest.TestCase):
    def test_add_reader(self):
        result = {'received': None}
        rsock, wsock = socketpair()
        self.addCleanup(rsock.close)
        self.addCleanup(wsock.close)

        def reader():
            data = rsock.recv(100)
            result['received'] = data
            self.loop.remove_reader(rsock)
            self.loop.stop()

        def writer():
            self.loop.remove_writer(wsock)
            self.loop.call_soon(wsock.send, b'abc')

        self.loop.add_reader(rsock, reader)
        self.loop.add_writer(wsock, writer)

        self.loop.run_forever()
        self.assertEqual(result['received'], b'abc')

    def check_add_replace(self, event):
        socket = self.config.socket

        selector = self.loop._selector
        if event == 'reader':
            add_sock = self.loop.add_reader
            remove_sock = self.loop.remove_reader
            def get_handle(fileobj):
                return selector.get_key(fileobj).data[0]
        else:
            add_sock = self.loop.add_writer
            remove_sock = self.loop.remove_writer
            def get_handle(fileobj):
                return selector.get_key(fileobj).data[1]

        sock = socket.socket()
        self.addCleanup(sock.close)

        def func():
            pass

        def func2():
            pass

        self.assertRaises(KeyError, get_handle, sock)

        add_sock(sock, func)
        handle1 = get_handle(sock)
        self.assertFalse(handle1._cancelled)

        add_sock(sock, func2)
        handle2 = get_handle(sock)
        self.assertIsNot(handle1, handle2)
        self.assertTrue(handle1._cancelled)
        self.assertFalse(handle2._cancelled)

        removed = remove_sock(sock)
        self.assertTrue(removed)
        self.assertTrue(handle2._cancelled)

        removed = remove_sock(sock)
        self.assertFalse(removed)

    def test_add_reader_replace(self):
        self.check_add_replace("reader")

    def test_add_writer_replace(self):
        self.check_add_replace("writer")


if __name__ == '__main__':
    import unittest
    unittest.main()
