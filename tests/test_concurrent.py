import trio
import trio_asyncio
import asyncio
import pytest

# Tests for concurrent or nested loops


@pytest.mark.trio
async def test_parallel():
    loops = [None, None]
    async with trio.open_nursery() as n:

        async def gen_loop(i, task_status=trio.TASK_STATUS_IGNORED):
            task_status.started()
            async with trio_asyncio.open_loop() as loop:
                loops[i] = loop

        assert not isinstance(asyncio._get_running_loop(), trio_asyncio.TrioEventLoop)
        await n.start(gen_loop, 0)
        await n.start(gen_loop, 1)

    assert isinstance(loops[0], trio_asyncio.TrioEventLoop)
    assert isinstance(loops[1], trio_asyncio.TrioEventLoop)
    assert loops[0] is not loops[1]


@pytest.mark.trio
async def test_nested():
    loops = [None, None]
    async with trio.open_nursery() as n:

        async def gen_loop(i, task_status=trio.TASK_STATUS_IGNORED):
            task_status.started()
            async with trio_asyncio.open_loop() as loop:
                loops[i] = loop
                if i > 0:
                    await n.start(gen_loop, i - 1)

        assert not isinstance(asyncio._get_running_loop(), trio_asyncio.TrioEventLoop)
        await n.start(gen_loop, 1)
    assert not isinstance(asyncio._get_running_loop(), trio_asyncio.TrioEventLoop)
    assert isinstance(loops[0], trio_asyncio.TrioEventLoop)
    assert isinstance(loops[1], trio_asyncio.TrioEventLoop)
    assert loops[0] is not loops[1]


async def _test_same_task():
    assert isinstance(asyncio.get_event_loop_policy(), trio_asyncio.TrioPolicy)

    def get_loop(i, loop, policy):
        assert loop == asyncio.get_event_loop()
        assert policy == asyncio.get_event_loop_policy()

    async with trio.open_nursery():
        async with trio_asyncio.open_loop() as loop1:
            policy = asyncio.get_event_loop_policy()
            assert isinstance(policy, trio_asyncio.TrioPolicy)
            async with trio_asyncio.open_loop() as loop2:
                p2 = asyncio.get_event_loop_policy()
                assert policy is p2, (policy, p2)
                loop1.call_later(0.1, get_loop, 0, loop1, policy)
                loop2.call_later(0.1, get_loop, 1, loop2, policy)
                await trio.sleep(0.2)

    assert isinstance(asyncio.get_event_loop_policy(), trio_asyncio.TrioPolicy)
    assert asyncio._get_running_loop() is None


def test_same_task():
    assert not isinstance(asyncio.get_event_loop_policy(), trio_asyncio.TrioPolicy)
    trio.run(_test_same_task)
