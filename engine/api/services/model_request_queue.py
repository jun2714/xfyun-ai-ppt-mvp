"""Bounded, fair admission for one API process/event loop.

This is not a durable or distributed job queue. Replicas must share a separate
admission service before their limits can be treated as account-wide limits.
"""
from __future__ import annotations

import asyncio
import math
import logging
import os
from collections import OrderedDict, Counter, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from weakref import WeakKeyDictionary

from fastapi import HTTPException
from api.v1.auth.context import get_current_owner_id
from utils.get_env import is_parallel_image_generation_enabled

LOGGER = logging.getLogger(__name__)


def _number(name, default, maximum):
    try:
        value = float(os.getenv(name, str(default)))
        return min(maximum, max(1, value)) if math.isfinite(value) else default
    except ValueError:
        return default


@dataclass(frozen=True)
class QueueLimits:
    concurrent: int
    per_owner: int
    pending: int
    wait_seconds: float
    per_owner_pending: int = 8


def queue_limits(lane: str) -> QueueLimits:
    prefix = "IMAGE" if lane == "image" else "OUTLINE"
    concurrent = int(_number(f"{prefix}_GLOBAL_CONCURRENCY", 2 if lane == "image" else 4, 16))
    if lane == "image" and not is_parallel_image_generation_enabled():
        concurrent = 1
    return QueueLimits(
        concurrent, min(concurrent, int(_number(f"{prefix}_PER_OWNER_CONCURRENCY", 1, 16))),
        int(_number(f"{prefix}_MAX_PENDING_REQUESTS", 32, 256)),
        _number(f"{prefix}_QUEUE_TIMEOUT_SECONDS", 180, 900),
        int(_number(f"{prefix}_PER_OWNER_MAX_PENDING", 8, 64)),
    )


class QueueBusy(HTTPException):
    def __init__(self, lane, *, expired=False):
        self.provider_code = f"{lane}_queue_timeout" if expired else f"{lane}_queue_full"
        super().__init__(
            status_code=503 if expired else 429,
            detail="生成排队等待超时，本次尚未提交供应商，请稍后再试。" if expired
            else "当前生成任务较多，本次尚未提交供应商，请稍后再试。",
            headers={"Retry-After": "15"},
        )


class FairRequestQueue:
    def __init__(self, lane: str, limits: QueueLimits):
        self.lane, self.limits = lane, limits
        self.active = 0
        self.owners = Counter()
        self.pending = OrderedDict()
        self.last_owner = None

    def _dispatch(self):
        while self.active < self.limits.concurrent and self.pending:
            eligible = [key for key in self.pending if self.owners[key] < self.limits.per_owner]
            owner = next((key for key in eligible if key != self.last_owner), eligible[0] if eligible else None)
            if owner is None:
                break
            requests = self.pending.pop(owner)
            entry = requests.popleft()
            if requests:
                self.pending[owner] = requests
            if entry[0].cancelled():
                continue
            entry[1] = True
            self.last_owner = owner
            self.active += 1
            self.owners[owner] += 1
            entry[0].set_result(None)

    @asynccontextmanager
    async def slot(self, owner):
        started = asyncio.get_running_loop().time()
        if (sum(map(len, self.pending.values())) >= self.limits.pending
                or len(self.pending.get(owner, ())) >= self.limits.per_owner_pending):
            raise QueueBusy(self.lane)
        entry = [asyncio.get_running_loop().create_future(), False]
        self.pending.setdefault(owner, deque()).append(entry)
        self._dispatch()
        try:
            try:
                async with asyncio.timeout(self.limits.wait_seconds):
                    await entry[0]
            except TimeoutError as exc:
                raise QueueBusy(self.lane, expired=True) from exc
            LOGGER.info("Model request admitted lane=%s queue_wait_seconds=%.3f active=%s",
                        self.lane, asyncio.get_running_loop().time() - started, self.active)
            yield
        finally:
            requests = self.pending.get(owner)
            if requests is not None and entry in requests:
                requests.remove(entry)
                if not requests:
                    self.pending.pop(owner)
            if entry[1]:
                self.active -= 1
                self.owners[owner] -= 1
                if not self.owners[owner]:
                    del self.owners[owner]
            self._dispatch()


_QUEUES = WeakKeyDictionary()


def get_request_queue(lane: str) -> FairRequestQueue:
    queues = _QUEUES.setdefault(asyncio.get_running_loop(), {})
    if lane not in queues:
        queues[lane] = FairRequestQueue(lane, queue_limits(lane))
    return queues[lane]


def model_request_slot(lane: str, fallback_owner="anonymous"):
    return get_request_queue(lane).slot(str(get_current_owner_id() or fallback_owner))
