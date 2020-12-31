from tests import aiotest
import pytest


def create_classes(config):
    asyncio = config.asyncio
    socket = config.socket
    threading = config.threading

    class TcpEchoClientProtocol(asyncio.Protocol):
        def __init__(self, message, loop):
            self.message = message
            self.loop = loop
            self.state = 'new'
            self.received = None

        def connection_made(self, transport):
            self.state = 'ping'
            transport.write(self.message)

        def data_received(self, data):
            self.state = 'pong'
            self.received = data

        def connection_lost(self, exc):
            self.state = 'closed'
            self.loop.stop()

    class TcpServer(threading.Thread):
        def __init__(self, host, port, event):
            super(TcpServer, self).__init__()
            self.host = host
            self.port = port
            self.event = event
            self.sock = None
            self.client = None

        def run(self):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock = sock
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((self.host, self.port))
                sock.listen(1)

                self.event.set()
                client, addr = sock.accept()
                self.client = client
                try:
                    message = client.recv(100)
                    client.sendall(message)
                finally:
                    client.close()
                    self.client = None
            finally:
                sock.close()
                self.sock = None

        def stop(self):
            self.join()

    return TcpEchoClientProtocol, TcpServer


class TestNetwork(aiotest.TestCase):
    @pytest.mark.trio
    async def test_tcp_hello(self, loop, config):
        return
        port = 8888
        host = '127.0.0.1'
        message = b'Hello World!'

        event = config.threading.Event()
        TcpEchoClientProtocol, TcpServer = create_classes(config)
        server = TcpServer(host, port, event)
        server.start()
        self.addCleanup(server.stop)
        event.wait()

        proto = TcpEchoClientProtocol(message, loop)
        coro = loop.create_connection(lambda: proto, host, port)
        await loop.run_aio_coroutine(coro)
        assert proto.state != 'new'

        await loop.stop().wait()()
        assert proto.state == 'closed'
        assert proto.received == message
