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
        self.detour_anchor = None
        self.attempt = 0
        self.next_side = 1
        self.route = deque()
        self.radius = 1.5

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
        if self.detour_anchor is None:
            self.detour_anchor = point
        anchor = self.detour_anchor
        center = center if center is not None else (point[0]-10, point[1])
        dx, dy = center[0]-anchor[0], center[1]-anchor[1]
        length = max(.001, math.hypot(dx, dy))
        dx, dy = dx/length, dy/length
        side = self.next_side
        self.next_side = -side
        sx, sy = -dy*side, dx*side
        # Try both sides at the same local scale before widening slightly.
        # Keep retries around the first obstruction, not ever farther away.
        base = max(1.5, min(2.1, (speed or 2.0)*.65))
        self.radius = radius = min(3.0, base+.35*((self.attempt-1)//2))
        def offset(forward, sideways):
            return (anchor[0]+radius*(dx*forward+sx*sideways),
                    anchor[1]+radius*(dy*forward+sy*sideways))
        retreat = offset(-.28, .55)
        control, end = offset(.05, 1.8), offset(.9, .4)
        self.route = deque([retreat])
        # A short diagonal retreat followed by a local curve around the obstacle.
        for t in (.25, .5, .75, 1.0):
            self.route.append(tuple((1-t)**2*retreat[i]+2*(1-t)*t*control[i]+t*t*end[i]
                                    for i in (0, 1)))
        self.reset_evidence(stamp+2)
        return 'a' if side > 0 else 'd'

    def escaping(self, point, stamp):
        return self.escape_target(point, stamp) is not None

    def escape_target(self, point, stamp):
        if self.escape_origin is None:
            return None
        while self.route and distance(point, self.route[0]) <= max(.35, self.radius*.15):
            self.route.popleft()
        if not self.route:
            self.escape_origin = None
            self.detour_anchor = None
            self.attempt = 0
            self.reset_evidence(stamp+2)
            return None
        return self.route[0]
