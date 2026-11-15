"""Feedback steering using W and camera turns; text always owns input first."""
from __future__ import annotations

import logging
import math
import threading
import time

from .coordinate_ocr import CoordinateOCR
from .platform_win import foreground_window, foreground_is_ours, screen_bounds, window_at_point, monitor_layout
from .position_model import PositionConfig, ReadingFilter, distance

LOGGER = logging.getLogger(__name__)


def signed_angle(value):
    return math.atan2(math.sin(value), math.cos(value))


class Steering:
    """Session-only movement observations; A/D are never treated as strafing."""
    def __init__(self):
        self.heading = None
        self.a_rate = None
        self.speed = None
        self.stationary = 0
        self.unproductive = 0

    def observe(self, before, after, center, turn=None, walk_seconds=None):
        delta = (after[0]-before[0], after[1]-before[1])
        length = math.hypot(*delta)
        if length < 0.09:
            self.stationary += 1
            return
        self.stationary = 0
        if walk_seconds and .2 <= length/walk_seconds <= 30:
            measured = length/walk_seconds
            self.speed = measured if self.speed is None else .6*self.speed+.4*measured
        heading = math.atan2(delta[1], delta[0])
        if turn is not None and self.heading is not None:
            key, seconds = turn
            change = signed_angle(heading-self.heading)
            if abs(change) > 0.03:
                rate = change/seconds * (1 if key == 'a' else -1)
                self.a_rate = rate
        elif self.heading is not None and abs(signed_angle(heading-self.heading)) > 0.7:
            # Manual camera changes invalidate the saved steering model.
            self.a_rate = None
        self.heading = heading
        if distance(after, center) >= distance(before, center)-0.05:
            self.unproductive += 1
        else:
            self.unproductive = 0

    def commands(self, point, config):
        margin = distance(point, config.center)-config.minimum
        walk = min(0.36, max(0.14, margin*0.04))
        if self.heading is None:
            return [('w', walk)]
        desired = math.atan2(config.center[1]-point[1], config.center[0]-point[0])
        error = signed_angle(desired-self.heading)
        if abs(error) <= 0.25:
            return [('w', walk)]
        if self.a_rate is None:
            turn = ('a', 0.18)
        else:
            turn = ('a' if error*self.a_rate > 0 else 'd',
                    min(0.28, max(0.12, abs(error/self.a_rate))))
        return [turn, ('w', walk)]


class PositionController:
    def __init__(self, engine, reader_factory=CoordinateOCR):
        self.engine = engine
        self.gate = engine.writing_gate
        self.reader_factory = reader_factory
        self.reader = None
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.thread = None
        self.config = PositionConfig()
        self.profile = None
        self.generation = 0
        self.snapshot = {'status': 'Alan seçin', 'available': None}
        self.target = None
        self.center_requested = False
        self.held_key = None
        self.reset_state()

    def reset_state(self):
        self.filter = ReadingFilter()
        self.steering = Steering()
        self.returning = False
        self.outside = self.inside = 0
        self.spent = 0.0
        self.failure = None
        self.last_epoch = 0.0
        self.pending_observation = None
        self._request_after = 0.0
        self.verified_count = 0
        self.estimate = None
        self.estimate_heading = None
        self.blind_spent = 0.0
        self.blind_until = 0.0

    def configure(self, profile, config):
        with self.lock:
            if self.profile == profile and self.config == config:
                return
            self.generation += 1
            self.profile = profile
            self.config = PositionConfig.from_dict(config.to_dict())
            self.center_requested = False
            self.target = None
            self.reset_state()
            self.snapshot = {'generation': self.generation, 'profile': profile,
                             'status': 'Konum okunuyor' if config.region else 'Alan seçin',
                             'available': None, 'point': None, 'distance': None}
            self.gate.position_enabled = self.config.enabled
            self.gate.set_position_blocked(self.config.enabled and self.engine.is_running)
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='position-controller', daemon=True)
                self.thread.start()
        self.wake.set()

    def state(self):
        with self.lock:
            return dict(self.snapshot)

    def publish(self, generation, **values):
        with self.lock:
            if generation == self.generation:
                self.snapshot.update(values)

    def request_center(self):
        with self.lock:
            self.center_requested = True
            self.filter = ReadingFilter()
            self.failure = None
            self.snapshot.pop('center_candidate', None)
            self.snapshot.pop('center_error', None)
            self._request_after = time.monotonic()
        self.wake.set()

    def running_changed(self, active):
        if active:
            self.target = None
        with self.gate.condition:
            self.gate.position_enabled = self.config.enabled
            self.gate.position_epoch = time.monotonic()
            self.gate.set_position_blocked(active and self.config.enabled)
        if not active:
            self.failure = None
            self.returning = False
            self.pending_observation = None
            self.outside = self.inside = 0
            self.spent = 0.0
            self.steering.stationary = self.steering.unproductive = 0
        self.wake.set()

    def allow_normal(self, generation, stamp):
        with self.gate.condition:
            if (generation == self.generation and stamp > self.gate.position_epoch
                    and not self.gate.writer_pending() and time.monotonic()-stamp <= .75):
                self.gate.set_position_blocked(False)

    def publish_failure(self, generation, status):
        self.failure = status
        self.gate.set_position_blocked(self.config.enabled and self.engine.is_running)
        self.publish(generation, status=status)

    def cancel_pulse(self, generation, stamp):
        return (self.closed.is_set() or generation != self.generation
                or not self.engine.is_running or not self.config.enabled
                or time.monotonic() > max(stamp+0.75, self.blind_until) or self.gate.writer_pending()
                or self.target is None or foreground_window() != self.target)

    def pulse(self, key, seconds, generation, stamp):
        cancelled = lambda: self.cancel_pulse(generation, stamp)
        with self.gate.movement(cancelled) as admitted:
            if not admitted:
                return False
            with self.engine.input_lock:
                if cancelled():
                    return False
                self.engine.mark_injected_key(key)
                self.engine.keyboard.press(key)
                self.held_key = key
                started = time.monotonic()
                try:
                    deadline = started + min(0.4, max(0, seconds))
                    while time.monotonic() < deadline:
                        if cancelled():
                            return False
                        self.closed.wait(min(0.01, max(0, deadline-time.monotonic())))
                    return True
                finally:
                    try:
                        self.engine.keyboard.release(key)
                    finally:
                        self.held_key = None
                        self.spent += time.monotonic()-started

    def evaluate(self, point, stamp, generation):
        config = self.config
        if not self.engine.is_running or not config.enabled:
            self.returning = False
            self.outside = self.inside = 0
            self.failure = None
            # Keep enabled navigation closed while stopped, including the
            # startup handover before the engine's enabled event is set.
            self.gate.set_position_blocked(config.enabled)
            self.publish(generation, status='Konum okunuyor' if config.center else 'Merkezi kaydedin')
            return
        if self.gate.writer_pending():
            self.publish(generation, status='Yazının bitmesi bekleniyor')
            return
        epoch = self.gate.position_epoch
        if epoch != self.last_epoch:
            self.pending_observation = None
            self.last_epoch = epoch
            self._request_after = max(self._request_after, epoch)
            self.verified_count = 0
            self.outside = self.inside = 0
        if stamp <= self._request_after or time.monotonic()-stamp > 0.75:
            self.gate.set_position_blocked(True)
            self.publish(generation, status='Güncel konum bekleniyor')
            return
        if self.failure:
            self.publish_failure(generation, self.failure)
            return
        current_window = foreground_window()
        if foreground_is_ours():
            self.gate.set_position_blocked(True)
            self.publish(generation, status='Oyun penceresine geçin')
            return
        if self.target is None:
            x, y, width, height = config.region
            candidate = window_at_point(x+width//2, y+height//2)
            if candidate is None or candidate != current_window:
                self.gate.set_position_blocked(True)
                self.publish(generation, status='Koordinatların olduğu oyun penceresine geçin')
                return
            self.target = candidate
            if self.engine._writing_target is None:
                self.engine._writing_target = candidate
        if current_window != self.target:
            self.gate.set_position_blocked(True)
            self.publish(generation, status='Oyun penceresine geçin')
            return
        gap = distance(point, config.center)
        self.verified_count += 1
        if self.pending_observation:
            before, ended, turn, walk_seconds = self.pending_observation
            if stamp <= ended+0.05:
                return
            self.steering.observe(before, point, config.center, turn, walk_seconds)
            self.pending_observation = None
        self.estimate = point
        self.estimate_heading = self.steering.heading
        self.blind_spent = 0.0
        if self.steering.stationary >= 3 or self.steering.unproductive >= 8 or self.spent >= 20:
            self.publish_failure(generation, 'Merkeze ulaşılamadı; karakteri ve konumu kontrol edin')
            return
        if not self.returning:
            self.outside = self.outside+1 if gap > config.maximum else 0
            if self.outside < 2:
                if self.outside:
                    self.gate.set_position_blocked(True)
                elif self.verified_count >= 2:
                    self.allow_normal(generation, stamp)
                else:
                    self.gate.set_position_blocked(True)
                self.publish(generation, status='Mesafe doğrulanıyor' if self.outside else 'Konum okunuyor')
                return
            self.returning = True
            self.spent = 0.0
        self.gate.set_position_blocked(True)
        self.inside = self.inside+1 if gap <= config.minimum else 0
        if self.inside:
            if self.inside >= 2:
                self.returning = False
                self.outside = self.inside = 0
                self.steering.stationary = self.steering.unproductive = 0
                self.allow_normal(generation, stamp)
                self.publish(generation, status='Merkeze ulaşıldı')
            return
        self.publish(generation, status='Merkeze dönüyor')
        turn = None
        walked = 0.0
        for key, duration in self.steering.commands(point, config):
            if not self.pulse(key, duration, generation, stamp):
                self.steering.heading = None
                return
            if key != 'w':
                turn = (key, duration)
                if self.estimate_heading is not None and self.steering.a_rate is not None:
                    self.estimate_heading += self.steering.a_rate*duration*(1 if key == 'a' else -1)
                else:
                    self.estimate_heading = None
            else:
                walked += duration
                self.advance_estimate(duration)
        self.pending_observation = (point, time.monotonic(), turn, walked)

    def advance_estimate(self, seconds):
        if self.estimate is not None and self.estimate_heading is not None and self.steering.speed:
            travel = seconds*self.steering.speed
            self.estimate = (self.estimate[0]+math.cos(self.estimate_heading)*travel,
                             self.estimate[1]+math.sin(self.estimate_heading)*travel)

    def continue_estimate(self, generation):
        """Bridge a short OCR gap; predictions can never release normal macros."""
        self.gate.set_position_blocked(self.config.enabled and self.engine.is_running)
        if (not self.returning or not self.engine.is_running or self.failure
                or not self.filter.last or generation != self.generation
                or self.gate.writer_pending()):
            return False
        point, stamp = self.filter.last
        if (stamp <= self.gate.position_epoch or time.monotonic()-stamp > 2.5
                or self.blind_spent >= .6 or self.target is None
                or foreground_window() != self.target):
            return False
        estimate = self.estimate or point
        gap = distance(estimate, self.config.center)-self.config.minimum
        if gap <= .75:
            return False
        heading = self.estimate_heading
        if heading is not None:
            desired = math.atan2(self.config.center[1]-estimate[1], self.config.center[0]-estimate[0])
            if abs(signed_angle(desired-heading)) > .5:
                return False
        elif self.pending_observation and self.pending_observation[2] is not None:
            # An unmeasured turn cannot justify a blind forward heading.
            return False
        seconds = min(.24, .6-self.blind_spent)
        if self.steering.speed:
            seconds = min(seconds, min(1.5-self.blind_spent*self.steering.speed, gap-.5)/self.steering.speed)
            if self.blind_spent*self.steering.speed >= 1.5:
                return False
        self.blind_until = min(stamp+2.5, time.monotonic()+seconds+.03)
        try:
            completed = self.pulse('w', seconds, generation, stamp)
        finally:
            self.blind_until = 0.0
        self.blind_spent += seconds
        if completed:
            self.advance_estimate(seconds)
            previous_walk = self.pending_observation[3] if self.pending_observation else 0
            self.pending_observation = (point, time.monotonic(), None, previous_walk+seconds)
            self.publish(generation, status='Konum tahminiyle ilerliyor')
        return completed

    def run(self):
        while not self.closed.is_set():
            self.wake.clear()
            started = time.monotonic()
            with self.lock:
                config, generation = self.config, self.generation
            if self.center_requested and started-self._request_after > 8:
                self.center_requested = False
                self.publish(generation, center_error='Merkez kaydedilemedi; karakteri sabit tutup yeniden deneyin.')
            if not config.region:
                self.wake.wait(0.5)
                continue
            if (config.display != screen_bounds() or
                    (config.monitors is not None and config.monitors != monitor_layout())):
                self.gate.set_position_blocked(config.enabled and self.engine.is_running)
                self.publish(generation, status='Ekran değişti; konumu yeniden seçin')
                self.wake.wait(0.5)
                continue
            if self.gate.writer_pending():
                self.publish(generation, status='Yazının bitmesi bekleniyor')
                self.wake.wait(0.05)
                continue
            try:
                if self.reader is None:
                    self.reader = self.reader_factory()
                    self.reader.start()
                    # Helper startup time must not age the first capture.
                    started = time.monotonic()
                point = self.reader.read(config.region)
                if generation != self.generation:
                    continue
                if self.center_requested and started <= self._request_after:
                    continue
                # An OCR frame captured before writing ended must not update
                # filtering, center candidates, or normal-input admission.
                if started <= self.gate.position_epoch and config.enabled and self.engine.is_running:
                    self.gate.set_position_blocked(True)
                    continue
                accepted = self.filter.accept(point, started, moving=self.returning,
                                               expected_speed=self.steering.speed)
                self.publish(generation, available=True)
                if not accepted or time.monotonic()-started > 0.75:
                    self.verified_count = 0
                    self.outside = self.inside = 0
                    self.gate.set_position_blocked(config.enabled and self.engine.is_running)
                    self.publish(generation, status='Konum değişti, merkezi kontrol edin' if self.filter.outliers >= 3 else 'Koordinat okunamıyor')
                    if self.filter.outliers >= 3:
                        self.failure = 'Konum değişti, merkezi kontrol edin'
                    self.continue_estimate(generation)
                else:
                    self.publish(generation, point=point, stamp=started,
                                 distance=distance(point, config.center) if config.center else None)
                    if self.center_requested and started > self._request_after and len(self.filter.stable) == 3:
                        self.center_requested = False
                        self.publish(generation, center_candidate=point, center_stamp=started)
                    self.gate.position_valid_until = started+0.75
                    self.evaluate(point, started, generation)
            except Exception as error:
                if self.closed.is_set():
                    break
                LOGGER.exception('Koordinat okuyucu başarısız')
                self.gate.set_position_blocked(config.enabled and self.engine.is_running)
                self.publish(generation, available=False,
                             status='Windows OCR kullanılamıyor; Windows OCR dilini kontrol edin',
                             error=str(error))
                self.wake.wait(5)
            self.wake.wait(max(0.01, 0.25-(time.monotonic()-started)))

    def stop(self):
        self.closed.set()
        self.wake.set()
        if self.reader is not None:
            self.reader.close()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        self.gate.position_enabled = False
        self.gate.set_position_blocked(False)
