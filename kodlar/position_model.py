"""Persistent per-profile position preferences and conservative numeric parsing."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re


@dataclass(slots=True)
class PositionConfig:
    enabled: bool = False
    region: tuple[int, int, int, int] | None = None
    display: tuple[int, int, int, int] | None = None
    center: tuple[float, float] | None = None
    maximum: float = 10.0
    minimum: float = 2.0
    monitors: tuple[tuple[int, int, int, int], ...] | None = None

    @property
    def ready(self):
        return bool(self.region and self.display and self.center is not None
                    and 0 <= self.minimum < self.maximum)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            return cls()
        try:
            maximum, minimum = float(raw.get('maximum', 10)), float(raw.get('minimum', 2))
            if not all(math.isfinite(v) for v in (maximum, minimum)) or not 0 <= minimum < maximum:
                maximum, minimum = 10.0, 2.0
            def coords(name, count, convert):
                value = raw.get(name)
                if not isinstance(value, (list, tuple)) or len(value) != count:
                    return None
                result = tuple(convert(v) for v in value)
                return result if all(math.isfinite(v) for v in result) else None
            region = coords('region', 4, int)
            display = coords('display', 4, int)
            center = coords('center', 2, float)
            if region and not (8 <= region[2] <= 640 and 8 <= region[3] <= 180):
                region = None
            if display and (display[2] <= 0 or display[3] <= 0):
                display = None
            if region and display:
                x, y, w, h = region
                left, top, width, height = display
                if not (left <= x and top <= y and x+w <= left+width and y+h <= top+height):
                    region = None
            config = cls(False, region, display, center, maximum, minimum)
            monitors = raw.get('monitors')
            if isinstance(monitors, (list, tuple)) and monitors:
                if all(isinstance(item, (list, tuple)) and len(item) == 4 for item in monitors):
                    config.monitors = tuple(tuple(int(v) for v in item) for item in monitors)
            config.enabled = bool(raw.get('enabled', False)) and config.ready
            return config
        except (ValueError, TypeError, OverflowError):
            return cls()


def parse_coordinates(text):
    # Do not invent missing decimal marks or pick two numbers out of a third.
    matches = []
    for line in str(text).replace(',', '.').splitlines():
        match = re.fullmatch(r'\s*([+-]?\d{1,5}\.\d)\s+([+-]?\d{1,5}\.\d)\s*', line)
        if match:
            matches.append(tuple(map(float, match.groups())))
    return matches[0] if len(matches) == 1 else None


def distance(first, second):
    return math.hypot(first[0]-second[0], first[1]-second[1])


class ReadingFilter:
    def __init__(self):
        self.last = None
        self.stable = []
        self.outliers = 0

    def accept(self, point, stamp):
        if point is None:
            self.stable.clear()
            return False
        if self.last:
            old, previous = self.last
            if distance(old, point) > max(3.0, (stamp-previous)*25):
                self.outliers += 1
                self.stable.clear()
                return False
        self.outliers = 0
        self.last = (point, stamp)
        if self.stable and any(distance(previous, point) > 0.3 for previous in self.stable):
            self.stable.clear()
        self.stable.append(point)
        self.stable = self.stable[-3:]
        return True
