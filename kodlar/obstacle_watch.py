"""Obstacle evidence uses actual displacement, never distance-to-center alone."""
from __future__ import annotations

from collections import deque
from .position_model import distance


class ObstacleWatch:
    def __init__(self):
        self.samples = deque(maxlen=40)
        self.cooldown = 0.0
        self.escape_origin = None
        self.escape_started = 0.0
        self.attempt = 0

    def reset_evidence(self, until=0.0):
        self.samples.clear()
        self.cooldown = max(self.cooldown, until)

    def stalled(self, point, stamp, *, walking, turning):
        if not walking or turning:
            self.reset_evidence(stamp+1.0)
            return False
        if stamp < self.cooldown:
            return False
        if self.samples and stamp-self.samples[-1][0] > 1.0:
            self.samples.clear()
        self.samples.append((stamp, point))
        while self.samples and stamp-self.samples[0][0] > 5.5:
            self.samples.popleft()
        if len(self.samples) < 8 or stamp-self.samples[0][0] < 4:
            return False
        origin = self.samples[0][1]
        return all(distance(origin, sample) <= .2 for _, sample in self.samples)

    def begin_escape(self, point, stamp):
        self.attempt += 1
        self.escape_origin = point
        self.escape_started = stamp
        self.reset_evidence(stamp+2)
        return 'a' if self.attempt % 2 else 'd'

    def escaping(self, point, stamp):
        if self.escape_origin is None:
            return False
        if distance(point, self.escape_origin) >= 1.0 or stamp-self.escape_started >= 3:
            self.escape_origin = None
            self.reset_evidence(stamp+2)
            return False
        return True
