import asyncio

import pytest

from services.model_request_queue import FairRequestQueue, QueueLimits, QueueBusy, model_request_slot
from api.v1.auth.context import set_current_owner_id, reset_current_owner_id


def test_teachers_take_turns_and_cancellation_does_not_leak_capacity():
    async def run():
        queue = FairRequestQueue('image', QueueLimits(1, 1, 10, 2))
        order = []
        async def work(owner):
            async with queue.slot(owner):
                order.append(owner)
                await asyncio.sleep(0)
        async with queue.slot('teacher-a'):
            tasks = [asyncio.create_task(work('teacher-a')) for _ in range(3)]
            tasks.append(asyncio.create_task(work('teacher-b')))
            cancelled = asyncio.create_task(work('teacher-c'))
            await asyncio.sleep(0)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
        await asyncio.gather(*tasks)
        assert order == ['teacher-b', 'teacher-a', 'teacher-a', 'teacher-a']
        assert queue.active == 0 and not queue.pending and not queue.owners
    asyncio.run(run())


def test_capacity_and_wait_deadline_reject_without_starting_work():
    async def run():
        queue = FairRequestQueue('image', QueueLimits(1, 1, 1, .02))
        async def must_not_start():
            async with queue.slot('b'):
                pytest.fail('Queued request must not reach provider')
        async with queue.slot('a'):
            waiting = asyncio.create_task(must_not_start())
            await asyncio.sleep(0)
            with pytest.raises(QueueBusy) as full:
                async with queue.slot('c'):
                    pytest.fail('Full queue must reject')
            assert full.value.provider_code == 'image_queue_full'
            with pytest.raises(QueueBusy) as expired:
                await waiting
            assert expired.value.provider_code == 'image_queue_timeout'
        async with queue.slot('d'):
            assert queue.active == 1
        assert not queue.pending and not queue.owners
    asyncio.run(run())


def test_many_teachers_share_global_and_per_owner_limits(monkeypatch):
    monkeypatch.setenv('IMAGE_GLOBAL_CONCURRENCY', '2')
    monkeypatch.setenv('IMAGE_PER_OWNER_CONCURRENCY', '1')
    monkeypatch.setenv('ENABLE_PARALLEL_IMAGE_GENERATION', 'true')
    async def run():
        active = 0
        peak = 0
        owners = set()
        async def work(owner):
            nonlocal active, peak
            token = set_current_owner_id(owner)
            try:
                async with model_request_slot('image'):
                    assert owner not in owners
                    owners.add(owner)
                    active += 1
                    peak = max(peak, active)
                    await asyncio.sleep(.002)
                    active -= 1
                    owners.remove(owner)
            finally:
                reset_current_owner_id(token)
        await asyncio.gather(*(work(f'teacher-{i % 5}') for i in range(20)))
        assert peak == 2 and active == 0
    asyncio.run(run())


def test_granted_but_cancelled_waiter_releases_slot():
    async def run():
        queue = FairRequestQueue('image', QueueLimits(1, 1, 8, 2))
        async def work():
            async with queue.slot('b'):
                await asyncio.Event().wait()
        async with queue.slot('a'):
            waiting = asyncio.create_task(work())
            await asyncio.sleep(0)
        waiting.cancel()  # Permit granted; waiter has not resumed yet.
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert queue.active == 0 and not queue.owners and not queue.pending
    asyncio.run(run())


def test_outline_admission_is_independent_of_saturated_image_queue(monkeypatch):
    monkeypatch.setenv('IMAGE_GLOBAL_CONCURRENCY', '1')
    async def run():
        async with model_request_slot('image'):
            async with model_request_slot('outline'):
                pass
    asyncio.run(asyncio.wait_for(run(), 1))
