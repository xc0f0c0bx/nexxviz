import random
import unittest

from beatclock import BeatClock


class TestBeatClock(unittest.TestCase):
    def test_wrap(self):
        c = BeatClock()
        c.update(0.0, 65534, 0.341, True)
        self.assertEqual(c.update(0.34, 65535, 0.341, True), 1)
        self.assertEqual(c.update(0.68, 0, 0.341, True), 1)

    def test_missed(self):
        c = BeatClock()
        c.update(0.0, 100, 0.341, True)
        self.assertEqual(c.update(1.0, 103, 0.341, True), 3)

    def test_jitter_phase(self):
        rng = random.Random(7)
        T = 60 / 176.0
        c = BeatClock()
        t = 0.0
        for k in range(1, 30):
            t = k * T + rng.uniform(0.0, 0.1706)
            c.update(t, 1000 + k, T, True)
        nxt = c.next_beat(t)
        err = abs(((nxt - 30 * T + T / 2) % T) - T / 2)
        self.assertLess(err, 0.020)
        self.assertGreater(c.confidence, 0.5)

    def test_pause(self):
        c = BeatClock()
        c.update(0.0, 5, 0.341, True)
        c.update(2.0, 5, 0.341, False)
        self.assertIsNone(c.next_beat(2.0))
        self.assertEqual(c.confidence, 0.0)

    def test_no_increments_free_runs(self):
        c = BeatClock()
        c.update(0.0, 5, 0.341, True)
        c.update(2.0, 5, 0.341, True)
        self.assertIsNotNone(c.next_beat(2.0))
        self.assertGreaterEqual(c.confidence, 0.2)
        self.assertLessEqual(c.confidence, 0.4)

    def test_tempo_change_clears_residuals(self):
        c = BeatClock()
        T = 0.34
        for k in range(1, 11):
            c.update(k * T, 100 + k, T, True)
        t = 10 * T + 0.001
        c.update(t, 110, T * 0.97, True)   # +3 % tempo, counter unchanged
        self.assertIsNone(c.next_beat(t))
        self.assertEqual(c.confidence, 0.0)

    def test_tempo_change_relocks(self):
        c = BeatClock()
        T = 0.34
        for k in range(1, 11):
            c.update(k * T, 100 + k, T, True)
        T2 = T * 0.97
        t = 10 * T
        for k in range(1, 5):
            t += T2
            c.update(t, 110 + k, T2, True)
        ph = c.phase(t)
        self.assertLess(min(ph, 1.0 - ph), 0.05)

    def test_track_change_reset(self):
        c = BeatClock()
        c.update(0.0, 5000, 0.341, True)
        self.assertEqual(c.update(0.34, 3, 0.341, True), 0)
        self.assertIsNone(c.next_beat(0.34))
        self.assertEqual(c.update(0.68, 4, 0.341, True), 1)

    def test_phase_advances_with_time(self):
        c = BeatClock()
        c.update(0.0, 10, 0.5, True)
        c.update(0.5, 11, 0.5, True)
        c.update(1.0, 12, 0.5, True)
        c.update(1.5, 13, 0.5, True)
        # anchor is the minimum-ish residual; verify phase wraps 0..1 and moves.
        p0 = c.phase(1.55)
        p1 = c.phase(1.80)
        self.assertGreaterEqual(p0, 0.0)
        self.assertLess(p0, 1.0)
        self.assertAlmostEqual((p1 - p0) % 1.0, 0.5, delta=0.02)

    def test_reset_clears(self):
        c = BeatClock()
        c.update(0.0, 10, 0.5, True)
        c.update(0.5, 11, 0.5, True)
        c.reset()
        self.assertIsNone(c.next_beat(0.5))
        self.assertEqual(c.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
