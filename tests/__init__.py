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
