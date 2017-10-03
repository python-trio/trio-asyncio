
# asyncio.loop logs some things we might need to see.
import logging
logging.basicConfig()
del logging

# asyncio runs many error messages through reprlib,
# which defaults to fairly short strings,
# which is a major PITA.
from reprlib import aRepr
aRepr.maxstring = 9999
aRepr.maxother = 9999
aRepr.maxlong = 9999
del aRepr

# Find the test SSL keys.
from asyncio import test_utils
def finish_request(self, request, client_address):
	import os
	import ssl
	here = os.path.join(os.path.dirname(__file__), 'python')
	keyfile = os.path.join(here, 'ssl_key.pem')
	certfile = os.path.join(here, 'ssl_cert.pem')
	context = ssl.SSLContext()
	context.load_cert_chain(certfile, keyfile)

	ssock = context.wrap_socket(request, server_side=True)
	try:
		self.RequestHandlerClass(ssock, client_address, self)
		ssock.close()
	except OSError:
		# maybe socket has been closed by peer
		pass
test_utils.SSLWSGIServerMixin.finish_request = finish_request
del test_utils
del finish_request

