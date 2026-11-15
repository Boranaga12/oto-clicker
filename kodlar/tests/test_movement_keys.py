from __future__ import annotations

import ctypes
import os
import unittest
from unittest.mock import Mock, patch

from kodlar import movement_keys


@unittest.skipUnless(os.name == 'nt', 'Windows physical keyboard injection')
class MovementKeyTests(unittest.TestCase):
    def test_game_input_uses_scan_code_and_matching_key_up_without_unicode(self):
        events = []
        native = Mock()

        def send(count, pointer, size):
            event = ctypes.cast(pointer, ctypes.POINTER(movement_keys.Input)).contents
            events.append((event.kind, event.data.keyboard.vk, event.data.keyboard.scan,
                           event.data.keyboard.flags, size))
            return count

        native.SendInput.side_effect = send
        fallback = Mock()
        with patch.object(movement_keys.ctypes, 'WinDLL', return_value=native):
            movement_keys.send_movement_key('w', True, fallback)
            movement_keys.send_movement_key('w', False, fallback)
        self.assertEqual(events, [(1, 0, 0x11, 0x8, ctypes.sizeof(movement_keys.Input)),
                                  (1, 0, 0x11, 0xa, ctypes.sizeof(movement_keys.Input))])
        self.assertEqual(ctypes.sizeof(movement_keys.Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        fallback.press.assert_not_called()
        fallback.release.assert_not_called()

    def test_failed_injection_is_reported_instead_of_claiming_w_is_held(self):
        native = Mock()
        native.SendInput.return_value = 0
        with patch.object(movement_keys.ctypes, 'WinDLL', return_value=native):
            with self.assertRaisesRegex(OSError, 'yetkilerini'):
                movement_keys.send_movement_key('w', True, Mock())
