from trio.tests.asyncio import aiotest

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


class NetworkTests(aiotest.TestCase):
    def test_tcp_hello(self):
        return
        port = 8888
        host = '127.0.0.1'
        message = b'Hello World!'

        event = self.config.threading.Event()
        TcpEchoClientProtocol, TcpServer = create_classes(self.config)
        server = TcpServer(host, port, event)
        server.start()
        self.addCleanup(server.stop)
        event.wait()

        proto = TcpEchoClientProtocol(message, self.loop)
        coro = self.loop.create_connection(lambda: proto, host, port)
        self.loop.run_until_complete(coro)
        self.assertNotEqual(proto.state, 'new')

        self.loop.run_forever()
        self.assertEqual(proto.state, 'closed')
        self.assertEqual(proto.received, message)


if __name__ == '__main__':
    import unittest
    unittest.main()
