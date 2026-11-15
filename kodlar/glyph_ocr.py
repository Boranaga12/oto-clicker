"""Small numeric-only recognizer: segmented glyphs, font shapes, real decimal dots."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import math
import statistics

GRID_W, GRID_H = 16, 24


@dataclass(frozen=True, slots=True)
class Glyph:
    left: int
    top: int
    width: int
    height: int
    pixels: tuple[tuple[int, ...], ...]
    kind: str = 'digit'


def components(mask):
    height, width = len(mask), len(mask[0])
    seen = set()
    result = []
    for y in range(height):
        for x in range(width):
            if not mask[y][x] or (x, y) in seen:
                continue
            pending = [(x, y)]
            seen.add((x, y))
            points = []
            while pending:
                px, py = pending.pop()
                points.append((px, py))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = px+dx, py+dy
                        if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and (nx, ny) not in seen:
                            seen.add((nx, ny))
                            pending.append((nx, ny))
            if len(points) < 1:
                continue
            left, right = min(p[0] for p in points), max(p[0] for p in points)
            top, bottom = min(p[1] for p in points), max(p[1] for p in points)
            pixels = tuple(tuple(mask[row][col] for col in range(left, right+1)) for row in range(top, bottom+1))
            result.append(Glyph(left, top, right-left+1, bottom-top+1, pixels))
    return sorted(result, key=lambda glyph: glyph.left)


def hole_count(pixels):
    height, width = len(pixels), len(pixels[0])
    seen, holes = set(), 0
    for y in range(height):
        for x in range(width):
            if pixels[y][x] or (x, y) in seen:
                continue
            queue, boundary = [(x, y)], False
            seen.add((x, y))
            while queue:
                px, py = queue.pop()
                boundary |= px in (0, width-1) or py in (0, height-1)
                for nx, ny in ((px-1, py), (px+1, py), (px, py-1), (px, py+1)):
                    if 0 <= nx < width and 0 <= ny < height and not pixels[ny][nx] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            holes += not boundary
    return holes


def fingerprint(glyph):
    bits = 0
    for y in range(GRID_H):
        sy = min(glyph.height-1, int((y+.5)*glyph.height/GRID_H))
        for x in range(GRID_W):
            sx = min(glyph.width-1, int((x+.5)*glyph.width/GRID_W))
            if glyph.pixels[sy][sx]:
                bits |= 1 << (y*GRID_W+x)
    return bits, glyph.width/glyph.height, hole_count(glyph.pixels)


def text_bands(mask):
    height, width = len(mask), len(mask[0])
    runs, start = [], None
    for y in range(height+1):
        ink = sum(mask[y]) if y < height else 0
        if ink >= max(2, width//70):
            if start is None:
                start = y
        elif start is not None:
            if 5 <= y-start <= 48:
                runs.append((start, y))
            start = None
    # A tight selection may contain only the text itself.
    return runs or [(0, height)]


def segment(plane, width, height, threshold):
    mask = [tuple(value >= threshold for value in plane[y*width:(y+1)*width]) for y in range(height)]
    for top, bottom in text_bands(mask):
        glyphs = components(mask[top:bottom])
        tall = [g for g in glyphs if g.height >= max(4, (bottom-top)*.55)]
        if not tall:
            continue
        line_height = statistics.median(g.height for g in tall)
        baseline = statistics.median(g.top+g.height for g in tall)
        tokens = []
        for glyph in glyphs:
            kind = 'digit'
            if glyph.height <= max(2, line_height*.3):
                if (glyph.width >= line_height*.4 and
                        baseline-line_height*.75 <= glyph.top <= baseline-line_height*.35):
                    kind = '-'
                elif glyph.top+glyph.height < baseline-line_height*.25 or glyph.width > line_height*.4:
                    continue
                else:
                    kind = '.'
            elif glyph.height < line_height*.55 or glyph.width > line_height*1.4:
                continue
            elif glyph.width <= glyph.height*.60:
                upper = [x for y, row in enumerate(glyph.pixels) for x, p in enumerate(row) if p and y < glyph.height*.35]
                lower = [x for y, row in enumerate(glyph.pixels) for x, p in enumerate(row) if p and y >= glyph.height*.65]
                if upper and lower and statistics.mean(upper)-statistics.mean(lower) >= 1.25:
                    kind = '/'
            tokens.append(Glyph(glyph.left, glyph.top+top, glyph.width, glyph.height, glyph.pixels, kind))
        if 5 <= len(tokens) <= 17:
            yield tokens


class GlyphReader:
    def __init__(self, templates=None):
        if templates is None:
            from .coordinate_font_data import TEMPLATES
            templates = TEMPLATES
        self.templates = [(label, int(bits, 16) if isinstance(bits, str) else bits, ratio, holes)
                          for label, bits, ratio, holes in templates]
        self.last_confidence = 0.0
        self.evidence = []

    def classify(self, glyph):
        bits, ratio, holes = fingerprint(glyph)
        scores = {}
        for label, sample, aspect, sample_holes in self.templates:
            # A complete pair of counters is strong positive evidence for 8.
            mismatch = (bits ^ sample).bit_count()/(GRID_W*GRID_H)
            score = mismatch + .10*min(1, abs(ratio-aspect)) + .035*min(2, abs(holes-sample_holes))
            if holes >= 2 and label != '8':
                score += .06
            if holes == 1 and label == '3':
                score += .045
            scores[label] = min(scores.get(label, math.inf), score)
        ranked = sorted(scores.items(), key=lambda item: item[1])
        if len(ranked) < 2:
            return None
        (label, score), (_, second) = ranked[:2]
        margin = second-score
        if score > .22 or margin < .018:
            return None
        return label, score, margin

    def read(self, plane, width, height):
        self.evidence = []
        self.last_confidence = 0.0
        if len(plane) != width*height or not 8 <= width <= 640 or not 8 <= height <= 180:
            return None
        candidates = []
        ordered = sorted(plane)
        low, high = ordered[len(ordered)//2], ordered[min(len(ordered)-1, int(len(ordered)*.985))]
        if high-low < 20:
            high = max(plane)
        adaptive = [round(low+(high-low)*fraction) for fraction in (.4, .55, .7)] if high-low >= 15 else []
        thresholds = sorted(set([90, 110, 130, 150, 170, 190, *adaptive]))
        for threshold in thresholds:
            for tokens in segment(plane, width, height, threshold):
                partial = [self.classify(glyph) for glyph in tokens if glyph.kind == 'digit']
                self.evidence.append(partial)
                chars, scores, margins = [], [], []
                for glyph in tokens:
                    if glyph.kind != 'digit':
                        chars.append(glyph.kind)
                        continue
                    digit = self.classify(glyph)
                    if digit is None:
                        break
                    chars.append(digit[0])
                    scores.append(digit[1])
                    margins.append(digit[2])
                else:
                    dots = [i for i, char in enumerate(chars) if char == '.']
                    if len(dots) != 2 or dots[0] < 1:
                        continue
                    split = dots[0]+2
                    if split >= len(chars) or chars[-2] != '.' or dots[1] <= split:
                        continue
                    left, right = ''.join(chars[:split]), ''.join(chars[split:])
                    if right.startswith('/'):
                        right = right[1:]
                    else:
                        gap = tokens[split].left-(tokens[split-1].left+tokens[split-1].width)
                        if gap < max(2, tokens[split-1].height*.2):
                            continue
                    from .position_model import parse_coordinates
                    point = parse_coordinates(left+' '+right)
                    if point is None or not scores:
                        continue
                    candidates.append((point, statistics.mean(scores), min(margins), threshold))
        if not candidates:
            return None
        # Vote by distinct preparations, then favor lower actual glyph error.
        votes = Counter(point for point, _, _, _ in candidates)
        winner, count = votes.most_common(1)[0]
        agreeing = [candidate for candidate in candidates if candidate[0] == winner]
        best = min(agreeing, key=lambda candidate: candidate[1])
        if count < 2 and not (best[1] < .045 and best[2] > .06):
            return None
        if len(votes) > 1 and count <= len(candidates)/2:
            return None
        self.last_confidence = 1-best[1]
        return winner

    def supports_native(self, point):
        digits = [char for char in f'{point[0]:.1f}{point[1]:.1f}' if char.isdigit()]
        contradictions = Counter()
        for sequence in self.evidence:
            if len(sequence) != len(digits):
                continue
            for index, (expected, observed) in enumerate(zip(digits, sequence)):
                if (observed is not None and observed[0] != expected
                        and observed[0] in '368' and expected in '368'
                        and observed[1] < .06 and observed[2] > .06):
                    contradictions[index] += 1
        return not any(count >= 2 for count in contradictions.values())
