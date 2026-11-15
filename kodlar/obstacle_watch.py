"""Obstacle evidence uses actual displacement, never distance-to-center alone."""
from __future__ import annotations

from collections import deque
import math
from .position_model import distance


class ObstacleWatch:
    def __init__(self):
        self.samples = deque(maxlen=40)
        self.cooldown = 0.0
        self.escape_origin = None
        self.escape_started = 0.0
        self.attempt = 0
        self.route = deque()
        self.radius = 6.0

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

    def begin_escape(self, point, stamp, center=None, speed=None):
        self.attempt += 1
        self.escape_origin = point
        self.escape_started = stamp
        center = center if center is not None else (point[0]-10, point[1])
        dx, dy = center[0]-point[0], center[1]-point[1]
        length = max(.001, math.hypot(dx, dy))
        dx, dy = dx/length, dy/length
        side = 1 if self.attempt % 2 else -1
        sx, sy = -dy*side, dx*side
        base = max(6.0, min(12.0, (speed or 2.0)*2.5))
        self.radius = radius = min(24.0, base*(1+.45*(self.attempt-1)))
        def offset(forward, sideways):
            return (point[0]+radius*(dx*forward+sx*sideways),
                    point[1]+radius*(dy*forward+sy*sideways))
        retreat = offset(-1.0, .35)
        control, end = offset(-.6, 2.6), offset(1.2, .45)
        self.route = deque([retreat])
        # Sample a broad quadratic curve after first turning away from the wall.
        for t in (.25, .5, .75, 1.0):
            self.route.append(tuple((1-t)**2*retreat[i]+2*(1-t)*t*control[i]+t*t*end[i]
                                    for i in (0, 1)))
        self.reset_evidence(stamp+2)
        return 'a' if self.attempt % 2 else 'd'

    def escaping(self, point, stamp):
        return self.escape_target(point, stamp) is not None

    def escape_target(self, point, stamp):
        if self.escape_origin is None:
            return None
        while self.route and distance(point, self.route[0]) <= max(.6, self.radius*.22):
            self.route.popleft()
        if not self.route:
            self.escape_origin = None
            self.reset_evidence(stamp+2)
            return None
        return self.route[0]
