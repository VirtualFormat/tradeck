"""滑动窗口配额单测（纯逻辑，假时钟）。"""

from __future__ import annotations

import unittest

from app.quota import SlidingWindowLimiter, retry_hint
from tests._helpers import FakeClock


class SlidingWindowTest(unittest.TestCase):
    def test_limit_and_retry_after(self) -> None:
        clock = FakeClock(0.0)
        lim = SlidingWindowLimiter(3, 60.0, clock)
        for _ in range(3):
            self.assertIsNone(lim.hit("k"))
            clock.advance(10)
        wait = lim.hit("k")  # t=30，最早一次在 t=0
        self.assertAlmostEqual(wait, 30.0)
        clock.advance(30)  # t=60：首个命中滑出窗口
        self.assertIsNone(lim.hit("k"))
        self.assertIsNotNone(lim.hit("k"))

    def test_rejected_hits_not_counted(self) -> None:
        clock = FakeClock(0.0)
        lim = SlidingWindowLimiter(1, 10.0, clock)
        self.assertIsNone(lim.hit("k"))
        for _ in range(5):
            self.assertIsNotNone(lim.hit("k"))
        clock.advance(10)
        self.assertIsNone(lim.hit("k"))

    def test_keys_isolated(self) -> None:
        lim = SlidingWindowLimiter(1, 60.0, FakeClock())
        self.assertIsNone(lim.hit("a"))
        self.assertIsNone(lim.hit("b"))
        self.assertIsNotNone(lim.hit("a"))

    def test_retry_hint(self) -> None:
        self.assertEqual(retry_hint(0.2), "1 秒")
        self.assertEqual(retry_hint(59.1), "60 秒")
        self.assertEqual(retry_hint(1800), "30 分钟")


if __name__ == "__main__":
    unittest.main()
