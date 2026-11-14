"""Cancellable FIFO ownership for complete chat transactions and paused clocks."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import threading
import time


class WritingGate:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.owner = None
        self.waiters = deque()
        self.active = 0
        self.normal_waiters = 0
        self.normal_budget = 0
        self.handoff_until = 0.0
        self.focus_check = None
        self.paused_total = 0.0
        self.paused_since = None

    def allowed(self):
        return self.owner == threading.get_ident() or (self.owner is None and (not self.waiters or self.normal_budget > 0 or time.monotonic() < self.handoff_until))

    @contextmanager
    def input(self, cancelled):
        admitted = False
        with self.condition:
            self.normal_waiters += 1
            try:
                while not cancelled() and not self.allowed():
                    self.condition.wait(0.02)
                if not cancelled():
                    self.active += 1
                    admitted = True
            finally:
                self.normal_waiters -= 1
                if self.normal_budget:
                    self.normal_budget -= 1
                self.condition.notify_all()
        try:
            yield admitted
        finally:
            if admitted:
                with self.condition:
                    self.active -= 1
                    self.condition.notify_all()

    @contextmanager
    def exclusive(self, cancelled):
        ticket = object()
        admitted = False
        with self.condition:
            self.waiters.append(ticket)
            try:
                while not cancelled():
                    if self.owner is None and self.waiters[0] is ticket and not self.active and not self.normal_budget and time.monotonic() >= self.handoff_until:
                        self.waiters.popleft()
                        self.owner = threading.get_ident()
                        self._finish_pause()
                        admitted = True
                        break
                    self.condition.wait(0.02)
            finally:
                if ticket in self.waiters:
                    self.waiters.remove(ticket)
                self._finish_pause()
                self.condition.notify_all()
        try:
            yield admitted
        finally:
            if admitted:
                with self.condition:
                    self.owner = None
                    if not self.waiters:
                        self.normal_budget = self.normal_waiters
                        # Give paused timers one scheduler turn before a fresh writer.
                        self.handoff_until = time.monotonic() + 0.01
                    self.focus_check = None
                    self._finish_pause()
                    self.condition.notify_all()

    def _finish_pause(self):
        paused = self.owner is not None
        if paused and self.paused_since is None:
            self.paused_since = time.monotonic()
        elif not paused and self.paused_since is not None:
            self.paused_total += time.monotonic()-self.paused_since
            self.paused_since = None

    def clock(self):
        with self.condition:
            now = time.monotonic()
            return now-self.paused_total-(now-self.paused_since if self.paused_since is not None else 0)

    def check_focus(self):
        if self.owner == threading.get_ident() and self.focus_check:
            self.focus_check()

    def wait(self, seconds, cancelled):
        remaining = max(0.0, seconds)
        first = True
        while first or remaining > 0:
            first = False
            with self.condition:
                while not cancelled() and not self.allowed():
                    self.condition.wait(0.02)
                if cancelled():
                    return True
                self.check_focus()
                started = time.monotonic()
                self.condition.wait(min(0.01, remaining))
                # A reservation ends this active slice; paused time never consumes the delay.
                if self.allowed():
                    remaining -= time.monotonic() - started
        return cancelled()
