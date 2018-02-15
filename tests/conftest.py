# XX this does not belong here -- b/c it's here, these things only apply to
# the tests in trio/_core/tests, not in trio/tests. For now there's some
# copy-paste...
#
# this stuff should become a proper pytest plugin

import pytest
import asyncio
import trio_asyncio


@pytest.fixture
async def loop():
    async with trio_asyncio.open_loop() as loop:
        try:
            yield loop
        finally:
            await loop.stop().wait()


@pytest.fixture
def sync_loop():
    loop = asyncio.new_event_loop()
    with loop:
        yield loop
