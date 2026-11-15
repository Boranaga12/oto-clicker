"""Own W continuously, correcting with A/D while yielding to writing in 10 ms."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time

from .platform_win import foreground_window

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WalkRequest:
    generation: int
    target: int
    epoch: float
    expires: float


class ContinuousWalker:
    def __init__(self, controller):
        self.controller = controller
        self.engine = controller.engine
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.thread = None
        self.request = None
        self.held = set()
        self.elapsed = 0.0
        self.started = None
        self.turn_request = None
        self.turn_serial = self.turn_seen = 0
        self.turn_end = 0.0

    @property
    def total(self):
        with self.lock:
            return self.elapsed+(time.monotonic()-self.started if self.started is not None else 0)

    @property
    def holding(self):
        with self.lock:
            return self.started is not None

    @property
    def turning(self):
        with self.lock:
            return self.turn_request is not None and (self.turn_seen != self.turn_serial or time.monotonic() < self.turn_end)

    def drive(self, generation, target, epoch, expires, turn=None):
        with self.lock:
            self.request = WalkRequest(generation, target, epoch, expires)
            if turn is not None and not self.turning:
                self.turn_serial += 1
                self.turn_request = turn
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='center-walking-input', daemon=True)
                self.thread.start()
        self.wake.set()

    def halt(self):
        with self.lock:
            self.request = None
            self.turn_request = None
        self.wake.set()

    def cancelled(self, admitted=None):
        with self.lock:
            request = self.request
        controller = self.controller
        return (self.closed.is_set() or request is None
            or (admitted is not None and (request.generation, request.target, request.epoch) !=
                (admitted.generation, admitted.target, admitted.epoch))
            or request.generation != controller.generation
            or request.epoch != self.engine.writing_gate.position_epoch
            or not self.engine.is_running or not controller.config.enabled or not controller.config.ready
            or time.monotonic() > request.expires or controller.failure is not None
            or self.engine.writing_gate.writer_pending()
            or foreground_window() != request.target)

    def press(self, key):
        with self.engine.input_lock:
            # Register ownership first so even a failing injection gets key-up.
            self.held.add(key)
            self.engine.mark_injected_key(key)
            self.engine.keyboard.press(key)

    def release(self, key):
        with self.engine.input_lock:
            if key in self.held:
                try:
                    self.engine.keyboard.release(key)
                finally:
                    self.held.discard(key)

    def release_owned(self):
        for key in tuple(self.held):
            try:
                self.release(key)
            except Exception:
                LOGGER.exception('Yürüyüş tuşu bırakılamadı: %s', key)

    def run(self):
        while not self.closed.is_set():
            self.wake.clear()
            if self.cancelled():
                self.wake.wait(.05)
                continue
            with self.lock:
                admitted_request = self.request
            cancel = lambda: self.cancelled(admitted_request)
            try:
                with self.engine.writing_gate.movement(cancel) as admitted:
                    if not admitted:
                        continue
                    try:
                        if cancel():
                            continue
                        with self.lock:
                            # Halt cannot report idle between the last intent
                            # check and the actual key-down registration.
                            if self.request is None or self.request.generation != admitted_request.generation:
                                continue
                            self.press('w')
                            self.started = time.monotonic()
                        while not cancel():
                            with self.lock:
                                serial, turn = self.turn_serial, self.turn_request
                            if turn is not None and serial != self.turn_seen:
                                self.release('a')
                                self.release('d')
                                if cancel():
                                    break
                                self.press(turn[0])
                                with self.lock:
                                    self.turn_end = time.monotonic()+min(1.2, max(.06, turn[1]))
                                    self.turn_seen = serial
                            if time.monotonic() >= self.turn_end:
                                self.release('a')
                                self.release('d')
                            self.wake.wait(.01)
                            self.wake.clear()
                    finally:
                        # The gate is released only after every owned key-up.
                        self.release_owned()
                        with self.lock:
                            if self.started is not None:
                                self.elapsed += time.monotonic()-self.started
                            self.started = None
                            self.turn_request = None
            except Exception:
                LOGGER.exception('Sürekli yürüyüş girdisi başarısız')
                self.controller.failure = 'Hareket gönderilemedi; oyunu kontrol edin'
                self.halt()

    def stop(self):
        self.closed.set()
        self.halt()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
