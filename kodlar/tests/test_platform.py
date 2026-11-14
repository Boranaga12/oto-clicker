from __future__ import annotations

import unittest

from kodlar.platform_win import SingleInstanceLock, is_color_close, parse_hex_color


class ColorTests(unittest.TestCase):
    def test_parse_color(self) -> None:
        self.assertEqual(parse_hex_color("#0a10ff"), (10, 16, 255))
        self.assertIsNone(parse_hex_color("red"))

    def test_color_tolerance(self) -> None:
        self.assertTrue(is_color_close("#101010", "#202020", threshold=16))
        self.assertFalse(is_color_close("#101010", "#301010", threshold=16))

    def test_single_instance_lock_can_be_reacquired_after_release(self) -> None:
        first = SingleInstanceLock("Local\\ArikMakroTest")
        second = SingleInstanceLock("Local\\ArikMakroTest")
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        second.release()

        third = SingleInstanceLock("Local\\ArikMakroTest")
        self.assertTrue(third.acquire())
        third.release()


if __name__ == "__main__":
    unittest.main()
