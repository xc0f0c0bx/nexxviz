import unittest

import story


class TestStory(unittest.TestCase):
    def test_starts_at_one(self):
        s = story.Story()
        st = s.update({"energy": 0.1}, 0.25)
        self.assertEqual(st["dim"], 1)
        self.assertEqual(st["brk"], 0.0)

    def test_advances_on_drop_after_minimum(self):
        s = story.Story()
        for _ in range(80):  # 20 s quiet
            s.update({"energy": 0.1}, 0.25)
        self.assertEqual(s.dim, 1)
        st = s.update({"energy": 0.5}, 0.25)  # drop 0.4
        self.assertEqual(st["dim"], 2)
        self.assertEqual(st["brk"], 0.0)

    def test_transition_has_no_break(self):
        s = story.Story()
        for _ in range(80):
            s.update({"energy": 0.1}, 0.25)
        s.update({"energy": 0.5}, 0.25)
        for _ in range(13):  # ~3.25 s
            st = s.update({"energy": 0.5}, 0.25)
        self.assertEqual(st["dim"], 2)
        self.assertEqual(st["brk"], 0.0)

    def test_dimension_glides(self):
        s = story.Story()
        for _ in range(80):
            s.update({"energy": 0.1}, 0.25)
        st = s.update({"energy": 0.5}, 0.25)
        self.assertEqual(st["dim"], 2)
        self.assertGreater(st["dim_v"], 1.0)
        self.assertLess(st["dim_v"], 2.0)

    def test_descends_when_quiet(self):
        s = story.Story()
        s.dim = 3
        s.t_ch = 12.0
        s.cooldown = 0.0
        st = s.update({"energy": 0.05}, 0.25)
        self.assertEqual(st["dim"], 2)

    def test_does_not_advance_above_thirteen(self):
        s = story.Story()
        s.dim = 13
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 13)

    def test_advances_from_six_to_seven(self):
        s = story.Story()
        s.dim = 6
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 7)
        self.assertEqual(st["brk"], 0.0)
        self.assertEqual(st["seal"], min(s.events, 6))

    def test_advances_from_twelve_to_thirteen(self):
        s = story.Story()
        s.dim = 12
        s.events = 11
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 13)
        self.assertEqual(st["seal"], 6)

    def test_seals_stay_open_above_seven(self):
        s = story.Story()
        s.dim = 9
        s.events = 9
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 10)
        self.assertEqual(st["seal"], 6)

    def test_fixed_dimension_override(self):
        st = story.apply_fixed(
            {"dim": 1, "brk": 1.0, "seal": 0, "energy": 0.5}, 13)
        self.assertEqual(st["dim"], 13)
        self.assertEqual(st["brk"], 0.0)
        self.assertEqual(st["seal"], 6)
        self.assertEqual(st["energy"], 0.5)
        self.assertEqual(story.apply_fixed({"dim": 2}, 0)["dim"], 2)

    def test_prime_ladder_rises_to_next_prime(self):
        s = story.Story(primes=True, start=13)
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 17)

    def test_prime_ladder_descends_to_previous_prime(self):
        s = story.Story(primes=True, start=17)
        s.t_ch = 12.0
        s.cooldown = 0.0
        st = s.update({"energy": 0.05}, 0.25)
        self.assertEqual(st["dim"], 13)

    def test_prime_ladder_starts_at_two(self):
        s = story.Story(primes=True)
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 2)

    def test_prime_ladder_stops_at_97(self):
        s = story.Story(primes=True, start=97)
        s.t_ch = 40.0
        s.cooldown = 0.0
        s.prev_e = 0.1
        st = s.update({"energy": 0.9}, 0.25)
        self.assertEqual(st["dim"], 97)

    def test_prime_start_at_thirteen_opens_seals(self):
        s = story.Story(primes=True, start=13)
        self.assertEqual(s.dim, 13)
        self.assertEqual(s.seal, 6)

    def test_prime_chase_moves_on_ordinary_music(self):
        s = story.Story(primes=True, start=13)
        s.t_ch = 27.0
        s.cooldown = 0.0
        s.prev_e = 0.3
        st = s.update({"energy": 0.3}, 0.25)
        self.assertEqual(st["dim"], 17)


if __name__ == "__main__":
    unittest.main()
