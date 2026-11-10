"""Shared rolling RPM/TPM reservations + bounded fair inflight scheduling."""
import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager


class LimitExceeded(ValueError):
    pass


class RateLimiter:
    def __init__(self, config, clock=time.monotonic, sleep=asyncio.sleep):
        self.config, self.clock, self.sleep = config, clock, sleep
        self.entries = deque()
        self.lock = asyncio.Lock()
        self.throttled_seconds = 0.0
        self.blocked_until = 0.0

    def block(self, seconds):
        self.blocked_until = max(self.blocked_until, self.clock() + seconds)

    async def reserve(self, pin, pout):
        c = self.config
        limits = [c.requests_per_minute, c.input_tokens_per_minute, c.output_tokens_per_minute, c.combined_tokens_per_minute]
        limits = [None if x is None else max(1, int(x * c.utilization_target)) for x in limits]
        request = [1, pin, pout, pin + pout]
        if any(limit is not None and amount > limit for limit, amount in zip(limits, request)):
            raise LimitExceeded('single_request_exceeds_quota')
        while True:
            async with self.lock:
                t = self.clock()
                while self.entries and self.entries[0][0] <= t - 60:
                    self.entries.popleft()
                totals = [sum(e[i + 1] for e in self.entries) for i in range(4)]
                wait = max(0, self.blocked_until - t)
                if any(lim is not None and total + amount > lim for lim, total, amount in zip(limits, totals, request)):
                    wait = max(wait, self.entries[0][0] + 60 - t)
                if wait <= 0:
                    entry = [t, *request]
                    self.entries.append(entry)
                    return entry
            self.throttled_seconds += wait
            await self.sleep(wait)

    def settle(self, entry, response):
        if response.input_tokens is not None:
            entry[2] = response.input_tokens
        if response.output_tokens is not None:
            entry[3] = response.output_tokens
        entry[4] = entry[2] + entry[3]


class InflightGate:
    """At most three S2 admissions while S1 waits; S2 priority only on backlog."""
    def __init__(self, capacity, prefer=True):
        self.capacity, self.prefer = capacity, prefer
        self.condition = asyncio.Condition()
        self.waiting = {1: deque(), 2: deque()}
        self.active = self.peak = self.s2_streak = 0

    def chosen(self, backlog):
        if not self.waiting[1]:
            return 2
        if not self.waiting[2]:
            return 1
        if self.prefer and backlog and self.s2_streak < 3:
            return 2
        return 1 if self.s2_streak else 2

    @asynccontextmanager
    async def slot(self, stage, backlogged=lambda: False):
        ticket = object()
        acquired = False
        async with self.condition:
            self.waiting[stage].append(ticket)
            try:
                await self.condition.wait_for(lambda: self.active < self.capacity and self.chosen(backlogged()) == stage and self.waiting[stage][0] is ticket)
                self.waiting[stage].popleft()
                self.active += 1
                acquired = True
                self.peak = max(self.peak, self.active)
                self.s2_streak = self.s2_streak + 1 if stage == 2 else 0
                self.condition.notify_all()
            except BaseException:
                if ticket in self.waiting[stage]:
                    self.waiting[stage].remove(ticket)
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            if acquired:
                async with self.condition:
                    self.active -= 1
                    self.condition.notify_all()
