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
        self.position_enabled = False
        self.position_blocked = False
        self.position_epoch = 0.0
        self.position_valid_until = 0.0

    def set_position_blocked(self, blocked):
        with self.condition:
            self.position_blocked = bool(blocked)
            self._finish_pause()
            self.condition.notify_all()

    def writer_pending(self):
        with self.condition:
            return self.owner is not None or bool(self.waiters)

    @contextmanager
    def movement(self, cancelled):
        admitted = False
        with self.condition:
            while not cancelled() and (self.owner is not None or self.waiters or self.active):
                self.condition.wait(0.01)
            if not cancelled():
                self.active += 1
                admitted = True
        try:
            yield admitted
        finally:
            if admitted:
                with self.condition:
                    self.active -= 1
                    self.condition.notify_all()

    def allowed(self):
        return self.owner == threading.get_ident() or (
            not self.position_blocked and self.owner is None
            and (not self.position_enabled or time.monotonic() <= self.position_valid_until)
            and (not self.waiters or (not self.position_enabled and
                 (self.normal_budget > 0 or time.monotonic() < self.handoff_until))))

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
                    position_wait = self.position_blocked or (self.position_enabled and time.monotonic() > self.position_valid_until)
                    fair_turn = self.position_enabled or position_wait or (not self.normal_budget and time.monotonic() >= self.handoff_until)
                    if self.owner is None and self.waiters[0] is ticket and not self.active and fair_turn:
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
                    if self.position_enabled:
                        # Block normal handoff until a capture made AFTER this
                        # writing transaction has been evaluated by navigation.
                        self.position_epoch = time.monotonic()
                        self.position_blocked = True
                    self.owner = None
                    if not self.waiters:
                        self.normal_budget = self.normal_waiters
                        # Give paused timers one scheduler turn before a fresh writer.
                        self.handoff_until = time.monotonic() + 0.01
                    self.focus_check = None
                    self._finish_pause()
                    self.condition.notify_all()

    def _finish_pause(self):
        paused = (self.owner is not None or self.position_blocked
                  or (self.position_enabled and time.monotonic() > self.position_valid_until))
        if paused and self.paused_since is None:
            self.paused_since = time.monotonic()
        elif not paused and self.paused_since is not None:
            self.paused_total += time.monotonic()-self.paused_since
            self.paused_since = None

    def clock(self):
        with self.condition:
            self._finish_pause()
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
