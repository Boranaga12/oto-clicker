"""Feedback steering using W and camera turns; text always owns input first."""
from __future__ import annotations

import logging
import math
import threading
import time

from .coordinate_ocr import CoordinateOCR, ocr_error_message
from .platform_win import foreground_window, foreground_is_ours, screen_bounds, window_at_point, monitor_layout
from .position_model import PositionConfig, ReadingFilter, distance
from .walking_input import ContinuousWalker
from .obstacle_watch import ObstacleWatch

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

    def correction(self, point, config):
        if self.heading is None:
            return None
        desired = math.atan2(config.center[1]-point[1], config.center[0]-point[0])
        error = signed_angle(desired-self.heading)
        if abs(error) <= 0.25:
            return None
        if self.a_rate is None:
            turn = ('a', 0.18)
        else:
            turn = ('a' if error*self.a_rate > 0 else 'd',
                    min(0.28, max(0.12, abs(error/self.a_rate))))
        return turn


class PositionController:
    FRESH_SECONDS = 1.5
    CENTER_TIMEOUT = 45.0

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
        self.motion = ContinuousWalker(self)
        self.reset_state()

    def reset_state(self):
        self.filter = ReadingFilter()
        self.steering = Steering()
        self.returning = False
        self.outside = self.inside = self.verified_count = 0
        self.outside_stamp = 0.0
        self.failure = None
        self.last_epoch = 0.0
        self._request_after = 0.0
        self.sample = None
        self.last_turn = None
        self.reading_lost = True
        self.obstacles = ObstacleWatch()
        self.arrival_pending = None

    def configure(self, profile, config):
        with self.lock:
            if self.profile == profile and self.config == config:
                return
            same_source = (self.profile == profile and self.config.region == config.region
                           and self.config.display == config.display and self.config.monitors == config.monitors)
            reader_state = {key: self.snapshot[key] for key in ('available', 'error', 'ocr_message')
                            if key in self.snapshot} if same_source else {}
            self.motion.halt()
            self.generation += 1
            self.profile = profile
            self.config = PositionConfig.from_dict(config.to_dict())
            self.center_requested = False
            self.target = None
            self.reset_state()
            self.snapshot = {'generation': self.generation, 'profile': profile,
                'status': 'Konum okunuyor' if config.region else 'Alan seçin',
                'available': None, 'point': None, 'distance': None}
            self.snapshot.update(reader_state)
            self.gate.position_enabled = self.config.enabled
            self.gate.navigation_active = False
            self.gate.set_position_blocked(False)
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='position-controller', daemon=True)
                self.thread.start()
        self.wake.set()

    def state(self):
        with self.lock:
            return dict(self.snapshot)

    def activation_issue(self, state=None):
        """Readiness never changes the user's enabled preference."""
        config = self.config
        state = self.state() if state is None else state
        if not config.region:
            return 'Konumu Seç ile koordinat alanını seçin.'
        if (config.display != screen_bounds() or
                (config.monitors is not None and config.monitors != monitor_layout())):
            return 'Bu bilgisayarın ekran düzeni farklı; Konumu Seç ile alanı yeniden seçin.'
        if state.get('available') is False:
            return state.get('ocr_message') or 'Windows OCR hazır değil; Yeniden Dene veya hata ayrıntısını kontrol edin.'
        if config.center is None:
            return 'Anlık Konumu Al ile merkezi kaydedin.'
        if not config.ready:
            return 'Mesafeleri kontrol edin: 0 ≤ Min < Maks olmalı.'
        if state.get('available') is not True:
            return 'Windows OCR hazırlanıyor; koordinat okuması bekleniyor.'
        return None

    def retry_ocr(self):
        if self.engine.is_running:
            return
        self.publish(self.generation, available=None, error=None, ocr_message=None,
                     status='Windows OCR yeniden deneniyor…')
        self.wake.set()

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
            self.snapshot['center_progress'] = 0
            self._request_after = time.monotonic()
        self.wake.set()

    def running_changed(self, active):
        self.motion.halt()
        self.sample = self.last_turn = None
        if active:
            self.target = None
        with self.gate.condition:
            self.gate.position_enabled = self.config.enabled
            self.gate.position_epoch = time.monotonic()
            self.gate.navigation_active = False
            self.gate.set_position_blocked(False)
        self.reading_lost = True
        if not active:
            self.failure = None
            self.returning = False
            self.outside = self.inside = 0
        self.wake.set()

    def allow_normal(self, generation, stamp):
        with self.gate.condition:
            if (generation == self.generation and stamp > self.gate.position_epoch
                    and not self.gate.writer_pending()
                    and time.monotonic()-stamp <= self.FRESH_SECONDS
                    and not self.motion.holding):
                self.gate.set_position_blocked(False)

    def publish_failure(self, generation, status):
        self.failure = status
        self.motion.halt()
        self.gate.set_position_blocked(self.config.enabled and self.engine.is_running)
        self.publish(generation, status=status)

    def bind_target(self, generation):
        current = foreground_window()
        if foreground_is_ours():
            self.publish(generation, status='Oyun penceresine geçin')
            return False
        if self.target is None:
            x, y, width, height = self.config.region
            candidate = window_at_point(x+width//2, y+height//2)
            if candidate is None or candidate != current:
                self.publish(generation, status='Koordinatların olduğu oyun penceresine geçin')
                return False
            self.target = candidate
            if self.engine._writing_target is None:
                self.engine._writing_target = candidate
        if current != self.target:
            self.publish(generation, status='Oyun penceresine geçin')
            return False
        return True

    def drive(self, generation, stamp, turn=None):
        if generation != self.generation or (not self.returning and stamp <= self.gate.position_epoch):
            return False
        self.gate.navigation_active = True
        self.gate.set_position_blocked(True)
        self.motion.drive(generation, self.target, self.gate.position_epoch,
                          float('inf') if self.returning else stamp+self.FRESH_SECONDS, turn)
        return True

    def mark_reading_lost(self, lost):
        changed = self.reading_lost != lost
        self.reading_lost = lost
        callback = getattr(self.engine, '_request_refresh', None)
        if changed and callback is not None:
            callback()

    def motion_released(self, generation, expired=False):
        if generation != self.generation:
            return
        if self.arrival_pending is not None:
            pending_generation, stamp = self.arrival_pending
            self.arrival_pending = None
            self.allow_normal(pending_generation, stamp)
            return
        if expired:
            self.mark_reading_lost(True)
        if self.reading_lost and not self.failure and not self.returning:
            self.gate.navigation_active = False
            self.gate.set_position_blocked(False)

    def release_on_read_loss(self, generation):
        if generation != self.generation:
            return
        self.mark_reading_lost(True)
        self.obstacles.reset_evidence()
        if self.returning and self.engine.is_running and self.config.enabled and self.config.ready and self.target is not None:
            self.drive(generation, time.monotonic())
            self.publish(generation, status='Merkeze dönüş kilitli; W basılı, koordinat aranıyor')
            return
        self.gate.navigation_active = False
        self.motion.halt()
        if not self.motion.holding:
            self.gate.set_position_blocked(False)
        self.publish(generation, status='Konum okunamıyor; normal makrolar devam ediyor')

    def evaluate(self, point, stamp, generation):
        if generation != self.generation:
            return
        config = self.config
        if not self.engine.is_running or not config.enabled or not config.ready:
            self.motion.halt()
            self.returning = False
            self.outside = self.inside = 0
            self.gate.navigation_active = False
            self.gate.set_position_blocked(False)
            self.publish(generation, status='Alan seçin' if not config.region else
                         'Merkezi kaydedin' if config.center is None else 'Konum okunuyor')
            return
        if self.gate.writer_pending():
            self.publish(generation, status='Yazının bitmesi bekleniyor')
            return
        epoch = self.gate.position_epoch
        if epoch != self.last_epoch:
            if not self.returning:
                self.motion.halt()
            self.last_epoch = epoch
            self._request_after = max(self._request_after, epoch)
            self.sample = self.last_turn = None
            self.verified_count = self.outside = self.inside = 0
        if stamp <= self._request_after or time.monotonic()-stamp > self.FRESH_SECONDS:
            self.gate.set_position_blocked(True)
            self.publish(generation, status='Güncel konum bekleniyor')
            return
        if self.failure:
            self.publish_failure(generation, self.failure)
            return
        if not self.bind_target(generation):
            self.release_on_read_loss(generation)
            self.sample = None
            return
        self.mark_reading_lost(False)
        total = self.motion.total
        gap = distance(point, config.center)
        self.verified_count += 1
        if self.sample is not None and self.motion.holding:
            before, previous, walked = self.sample
            dt = total-walked
            if dt >= .08 and stamp > previous:
                turn = None
                if self.last_turn and not self.motion.turning:
                    turn = self.last_turn
                    self.last_turn = None
                self.steering.observe(before, point, config.center, turn, dt)
        self.sample = (point, stamp, total)
        if not self.returning:
            if gap > config.maximum:
                self.outside = self.outside+1 if stamp-self.outside_stamp <= 4 else 1
                self.outside_stamp = stamp
                self.returning = True
                self.steering.stationary = self.steering.unproductive = 0
                self.obstacles = ObstacleWatch()
            else:
                self.outside = 0
                self.gate.navigation_active = False
                if self.verified_count >= 2:
                    self.allow_normal(generation, stamp)
                self.publish(generation, status='Konum okunuyor')
                return
        self.gate.set_position_blocked(True)
        if gap < config.minimum or gap == config.minimum == 0:
            self.motion.halt()
            self.returning = False
            self.gate.navigation_active = False
            self.outside = self.inside = 0
            self.arrival_pending = (generation, stamp)
            if not self.motion.holding:
                self.arrival_pending = None
                self.allow_normal(generation, stamp)
            self.publish(generation, status='Merkeze ulaşıldı')
            return
        self.inside = 0
        if self.obstacles.escaping(point, stamp):
            self.drive(generation, stamp)
            self.publish(generation, status='Engelin çevresinden yürüyor')
            return
        if self.obstacles.stalled(point, stamp, walking=self.motion.holding, turning=self.motion.turning):
            direction = self.obstacles.begin_escape(point, stamp)
            rate = abs(self.steering.a_rate) if self.steering.a_rate else 2.2
            turn = (direction, min(.65, max(.15, (math.pi/4)/rate)))
            self.last_turn = turn
            self.steering.stationary = 0
            if self.steering.heading is not None and self.steering.a_rate is not None:
                self.steering.heading += self.steering.a_rate*turn[1]*(1 if direction == 'a' else -1)
            self.drive(generation, stamp, turn)
            self.publish(generation, status='Engel için sola sapıyor' if turn[0] == 'a' else 'Engel için sağa sapıyor')
            return
        turn = None
        if not self.motion.turning and self.steering.stationary < 2:
            turn = self.steering.correction(point, config)
            if turn is not None:
                self.last_turn = turn
                self.obstacles.reset_evidence(stamp+1.0)
        self.drive(generation, stamp, turn)
        self.publish(generation, status='Merkeze dönüyor')

    def missing_reading(self, generation):
        # Do not erase an earlier trusted outside-Max reading on every OCR miss.
        self.verified_count = 0
        self.inside = 0
        self.release_on_read_loss(generation)

    def run(self):
        while not self.closed.is_set():
            self.wake.clear()
            started = time.monotonic()
            with self.lock:
                config, generation = self.config, self.generation
            if self.center_requested and started-self._request_after > self.CENTER_TIMEOUT:
                self.center_requested = False
                self.publish(generation, center_error='Merkez kaydedilemedi; yalnızca iki koordinatı çevreleyen dar bir alan seçip karakteri sabit tutarak yeniden deneyin.')
            if not config.region:
                self.motion.halt()
                self.wake.wait(.5)
                continue
            if (config.display != screen_bounds() or
                    (config.monitors is not None and config.monitors != monitor_layout())):
                self.release_on_read_loss(generation)
                self.publish(generation, status='Ekran değişti; konumu yeniden seçin')
                self.wake.wait(.5)
                continue
            if self.gate.writer_pending():
                self.publish(generation, status='Yazının bitmesi bekleniyor')
                self.wake.wait(.05)
                continue
            try:
                if self.reader is None:
                    self.reader = self.reader_factory()
                    self.reader.start()
                point = self.reader.read(config.region)
                stamp = getattr(self.reader, 'capture_stamp', started)
                if generation != self.generation:
                    continue
                if self.center_requested and stamp <= self._request_after:
                    continue
                if stamp <= self.gate.position_epoch and config.enabled and self.engine.is_running:
                    self.missing_reading(generation)
                    continue
                accepted = self.filter.accept(point, stamp, moving=self.motion.holding,
                                               expected_speed=self.steering.speed)
                self.publish(generation, available=True, error=None, ocr_message=None)
                if self.center_requested:
                    self.publish(generation, center_progress=len(self.filter.stable))
                if not accepted or time.monotonic()-stamp > self.FRESH_SECONDS:
                    self.missing_reading(generation)
                else:
                    self.publish(generation, point=point, stamp=stamp,
                                 distance=distance(point, config.center) if config.center else None)
                    if self.center_requested and stamp > self._request_after and len(self.filter.stable) == 3:
                        self.center_requested = False
                        self.publish(generation, center_candidate=point, center_stamp=stamp)
                    self.gate.position_valid_until = stamp+self.FRESH_SECONDS
                    self.evaluate(point, stamp, generation)
            except Exception as error:
                if self.closed.is_set():
                    break
                LOGGER.exception('Koordinat okuyucu başarısız')
                self.release_on_read_loss(generation)
                self.publish(generation, available=False,
                             status=ocr_error_message(error), ocr_message=ocr_error_message(error),
                             error=str(error).strip() or type(error).__name__)
                self.wake.wait(2)
            self.wake.wait(max(.01, .25-(time.monotonic()-started)))

    def stop(self):
        self.closed.set()
        self.wake.set()
        self.motion.stop()
        if self.reader is not None:
            self.reader.close()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        self.gate.position_enabled = False
        self.gate.set_position_blocked(False)
