from __future__ import annotations

import unittest
import io
import base64
import json
import queue
from types import SimpleNamespace
from unittest.mock import Mock
from itertools import product

from kodlar.coordinate_font_data import TEMPLATES
from kodlar.glyph_ocr import GlyphReader, GRID_W, GRID_H
from kodlar.obstacle_watch import ObstacleWatch
from kodlar.coordinate_ocr import CoordinateOCR


def render_numbers(text, *, brightness=255, scale=1):
    """Compose new coordinates from individual glyphs, never whole screenshots."""
    forms = {}
    expected_holes = {'0': 1, '3': 0, '6': 1, '8': 2, '9': 1}
    for label in '0123456789':
        candidates = [template for template in TEMPLATES if template[0] == label
                      and template[3] == expected_holes.get(label, 0)]
        forms[label] = min(candidates, key=lambda template: abs(template[2]-.65))
    glyphs = []
    for char in text:
        if char.isdigit():
            bits = int(forms[char][1], 16)
            glyphs.append([[brightness if bits & (1 << (y*GRID_W+x)) else 20
                            for x in range(GRID_W)] for y in range(GRID_H)])
        elif char == '.':
            glyphs.append([[brightness if y >= GRID_H-2 else 20 for _ in range(2)] for y in range(GRID_H)])
        elif char == '/':
            glyphs.append([[brightness if 3 <= y < 21 and x == 5-(y-3)//3 else 20 for x in range(6)]
                           for y in range(GRID_H)])
        elif char == ' ':
            glyphs.append([[20]*5 for _ in range(GRID_H)])
    width = sum(len(glyph[0])+3 for glyph in glyphs)+6
    height = GRID_H+6
    plane = [[20]*width for _ in range(height)]
    left = 3
    for glyph in glyphs:
        for y, row in enumerate(glyph):
            plane[y+2][left:left+len(row)] = row
        left += len(glyph[0])+3
    expanded = [value for row in plane for _ in range(scale) for value in row for _ in range(scale)]
    return bytes(expanded), width*scale, height*scale


class NumericGlyphTests(unittest.TestCase):
    def test_capture_can_be_read_without_installed_native_ocr_language(self):
        plane, width, height = render_numbers('88.8 / 66.6')
        reader = CoordinateOCR()
        reader.start = Mock()
        reader.native_available = False
        reader.process = SimpleNamespace(stdin=io.StringIO())
        reader.responses = queue.Queue()
        reader.responses.put({'id': 1, 'pixels': base64.b64encode(plane).decode(), 'age_ms': 0})
        self.assertEqual(reader.read((0, 0, width, height)), (88.8, 66.6))
        requests = reader.process.stdin.getvalue().splitlines()
        self.assertEqual(len(requests), 1)
        self.assertEqual(json.loads(requests[0])['mode'], 'capture')

    def test_native_fallback_uses_the_same_capture_id(self):
        reader = CoordinateOCR()
        reader.start = Mock()
        reader.glyphs.read = Mock(return_value=None)
        reader.process = SimpleNamespace(stdin=io.StringIO())
        reader.responses = queue.Queue()
        reader.responses.put({'id': 1, 'pixels': base64.b64encode(bytes(64)).decode(), 'age_ms': 0})
        reader.responses.put({'id': 2, 'texts': ['85.3 / 50.8', '85.3 50.8'], 'indices': [0, 1], 'age_ms': 0})
        self.assertEqual(reader.read((0, 0, 8, 8)), (85.3, 50.8))
        requests = [json.loads(line) for line in reader.process.stdin.getvalue().splitlines()]
        self.assertEqual(requests[1]['capture_id'], requests[0]['id'])
    def test_unseen_combinations_of_three_six_eight_and_contrast(self):
        reader = GlyphReader()
        values = ('33.3', '36.6', '38.8', '63.6', '66.3', '68.8', '83.8', '86.3', '88.6')
        for index, (left, right) in enumerate(product(values, repeat=2)):
            with self.subTest(x=left, y=right):
                plane, width, height = render_numbers(left+' / '+right, brightness=(110, 170, 255)[index%3])
                self.assertEqual(reader.read(plane, width, height), (float(left), float(right)))

    def test_all_digits_scales_and_real_decimal_requirement(self):
        reader = GlyphReader()
        for text in ('12.4 / 90.7', '85.3 / 50.8', '36.8 / 63.8', '0.0 / 99.9'):
            for scale in (1, 2):
                with self.subTest(text=text, scale=scale):
                    plane, width, height = render_numbers(text, scale=scale)
                    expected = tuple(map(float, text.split('/')))
                    self.assertEqual(reader.read(plane, width, height), expected)
        plane, width, height = render_numbers('853 / 50.8')
        self.assertIsNone(reader.read(plane, width, height))

    def test_native_three_cannot_override_clear_eight_glyphs(self):
        reader = GlyphReader()
        plane, width, height = render_numbers('88.8 / 66.6')
        self.assertEqual(reader.read(plane, width, height), (88.8, 66.6))
        self.assertFalse(reader.supports_native((33.3, 66.6)))
        self.assertTrue(reader.supports_native((88.8, 66.6)))


class ObstacleEvidenceTests(unittest.TestCase):
    def test_moving_away_from_center_is_not_an_obstacle(self):
        watch = ObstacleWatch()
        for index in range(30):
            self.assertFalse(watch.stalled((10+index*.2, 0), index*.25, walking=True, turning=False))

    def test_turns_and_missing_intervals_cannot_create_an_obstacle(self):
        watch = ObstacleWatch()
        for index in range(20):
            self.assertFalse(watch.stalled((10, 0), index*.25, walking=True, turning=True))
        for index in range(10):
            self.assertFalse(watch.stalled((10, 0), 10+index*2, walking=True, turning=False))

    def test_only_sustained_stationary_readings_trigger_alternating_escape(self):
        watch = ObstacleWatch()
        results = [watch.stalled((10, 0), index*.25, walking=True, turning=False) for index in range(18)]
        self.assertFalse(any(results[:16]))
        self.assertTrue(results[-1])
        self.assertEqual(watch.begin_escape((10, 0), 5), 'a')
        self.assertTrue(watch.escaping((10.1, 0), 6))
        self.assertFalse(watch.escaping((11.1, 0), 6.5))
        self.assertEqual(watch.begin_escape((11.1, 0), 10), 'd')
