from __future__ import absolute_import
from tests.aiotest import socketpair
import pytest
import trio


class TestAddReader:
    @pytest.mark.trio
    async def test_add_reader(self, loop):
        result = {'received': None}
        rsock, wsock = socketpair()
        ready = trio.Event()
        try:

            def reader():
                data = rsock.recv(100)
                result['received'] = data
                loop.remove_reader(rsock)
                ready.set()

            def writer():
                loop.remove_writer(wsock)
                loop.call_soon(wsock.send, b'abc')

            loop.add_reader(rsock, reader)
            loop.add_writer(wsock, writer)

            await ready.wait()
            assert result['received'] == b'abc'

        finally:
            rsock.close()
            wsock.close()

    async def check_add_replace(self, event, loop, config):
        socket = config.socket

        selector = loop._selector
        if event == 'reader':
            add_sock = loop.add_reader
            remove_sock = loop.remove_reader

            def get_handle(fileobj):
                return selector.get_key(fileobj).data[0]
        else:
            add_sock = loop.add_writer
            remove_sock = loop.remove_writer

            def get_handle(fileobj):
                return selector.get_key(fileobj).data[1]

        sock = socket.socket()
        try:

            def func():
                pass

            def func2():
                pass

            with pytest.raises(KeyError):
                get_handle(sock)

            add_sock(sock, func)
            handle1 = get_handle(sock)
            assert not handle1._cancelled

            add_sock(sock, func2)
            handle2 = get_handle(sock)
            assert handle1 is not handle2
            assert handle1._cancelled
            assert not handle2._cancelled

            removed = remove_sock(sock)
            assert removed
            assert handle2._cancelled

            removed = remove_sock(sock)
            assert not removed
        finally:
            sock.close()

    @pytest.mark.trio
    async def test_add_reader_replace(self, loop, config):
        await self.check_add_replace("reader", loop, config)

    @pytest.mark.trio
    async def test_add_writer_replace(self, loop, config):
        await self.check_add_replace("writer", loop, config)
