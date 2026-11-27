import random
import tempfile
import unittest
from pathlib import Path

import evolve


class TestGenome(unittest.TestCase):
    def test_random_in_bounds(self):
        rng = random.Random(1)
        for _ in range(20):
            g = evolve.random_genome(rng)
            self.assertEqual(len(g), 8)
            for v, (lo, hi) in zip(g, evolve.BOUNDS):
                self.assertGreaterEqual(v, lo)
                self.assertLessEqual(v, hi)

    def test_mutate_bounds(self):
        rng = random.Random(2)
        g = evolve.random_genome(rng)
        for _ in range(100):
            g = evolve.mutate(g, rng)
            for v, (lo, hi) in zip(g, evolve.BOUNDS):
                self.assertGreaterEqual(v, lo)
                self.assertLessEqual(v, hi)

    def test_fitness_range(self):
        feat = {"flatness": 0.5, "centroid": 0.5, "energy": 0.5, "conf": 0.5}
        for seed in range(20):
            f = evolve.fitness(evolve.random_genome(random.Random(seed)), feat)
            self.assertGreaterEqual(f, 0.0)
            self.assertLessEqual(f, 1.0)

    def test_evolve_size_elite(self):
        rng = random.Random(4)
        pop = [evolve.random_genome(rng) for _ in range(12)]
        feat = {"flatness": 0.9, "centroid": 0.2, "energy": 1.0, "conf": 1.0}
        best, newpop = evolve.evolve(pop, feat, rng)
        self.assertEqual(len(newpop), 12)
        self.assertIn(best, newpop)
        self.assertEqual(best, max(pop, key=lambda g: evolve.fitness(g, feat)))


class TestFeatures(unittest.TestCase):
    def test_all_loud(self):
        f = evolve.features_from_bytes(bytes([255]) * 36)
        self.assertAlmostEqual(f["energy"], 1.0, delta=0.02)
        self.assertAlmostEqual(f["flatness"], 1.0, delta=0.02)
        self.assertAlmostEqual(f["conf"], 1.0, delta=0.02)

    def test_silence(self):
        f = evolve.features_from_bytes(bytes(36))
        self.assertEqual(f["energy"], 0.0)
        self.assertEqual(f["flatness"], 0.0)
        self.assertEqual(f["conf"], 0.0)

    def test_read_write(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "genome"
            g = [420.0, 6.0, 0.66, 0.9, 1.35, 1.1, 0.82, 0.35]
            evolve.write_genome(p, g)
            self.assertEqual([float(x) for x in p.read_text().split()], g)
            spec = Path(td) / "spectrum"
            spec.write_bytes(bytes([128]) * 36)
            f = evolve.read_features(spec)
            self.assertGreater(f["energy"], 0.4)
            self.assertEqual(evolve.read_features(Path(td) / "missing")["energy"], 0.0)


class TestPreference(unittest.TestCase):
    FEAT = {"flatness": 0.5, "centroid": 0.5, "energy": 0.5, "conf": 0.5}

    def test_learns_like_vs_dislike(self):
        model = evolve.PreferenceModel(lr=0.4)
        liked = [420.0, 3.0, 0.35, 0.15, 0.60, 1.50, 0.98, 0.70]
        disliked = [80.0, 12.0, 0.95, 1.20, 2.00, 0.40, 0.65, 0.00]
        for _ in range(40):
            model.update(liked, self.FEAT, 1)
            model.update(disliked, self.FEAT, -1)
        self.assertGreater(model.predict(liked, self.FEAT),
                           model.predict(disliked, self.FEAT) + 0.2)
        self.assertEqual(model.n, 80)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "model.json"
            m = evolve.PreferenceModel([0.1] * evolve.N_FEATURES, 7)
            m.save(p)
            m2 = evolve.PreferenceModel.load(p)
            self.assertEqual(m2.n, 7)
            self.assertAlmostEqual(m2.w[0], 0.1)
            self.assertEqual(evolve.PreferenceModel.load(Path(td) / "missing").n, 0)

    def test_combined_fitness_blends(self):
        g = evolve.DEFAULTS
        model = evolve.PreferenceModel([1.0] * evolve.N_FEATURES, 10)
        self.assertNotAlmostEqual(
            evolve.fitness(g, self.FEAT),
            evolve.fitness_with_model(g, self.FEAT, model), places=4)
        self.assertAlmostEqual(evolve.fitness_with_model(g, self.FEAT, None),
                               evolve.fitness(g, self.FEAT))

    def test_parse_feedback(self):
        g = evolve.DEFAULTS
        line = ('{"reward": 1, "genome": ' + str(g).replace("'", "") +
                ', "features": {"flatness": 0.4, "centroid": 0.2, '
                '"energy": 0.8, "conf": 0.6}}')
        parsed = evolve.parse_feedback(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], g)
        self.assertEqual(parsed[2], 1)
        self.assertAlmostEqual(parsed[1]["energy"], 0.8)
        self.assertIsNone(evolve.parse_feedback("not json"))
        self.assertIsNone(evolve.parse_feedback('{"reward": 0, "genome": []}'))

    def test_train_and_offset(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "feedback"
            g = evolve.DEFAULTS
            line = ('{"reward": -1, "genome": ' + str(g).replace("'", "") + '}\n')
            p.write_text(line)
            lines, off = evolve.read_new_feedback(p, 0)
            self.assertEqual(len(lines), 1)
            self.assertEqual(off, len(line))
            self.assertEqual(evolve.read_new_feedback(p, off)[0], [])
            model = evolve.PreferenceModel()
            self.assertEqual(evolve.train_feedback(model, lines), 1)
            self.assertEqual(model.n, 1)


class TestEntropy(unittest.TestCase):
    def test_read_urandom_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ent"
            p.write_bytes(b"\x01\x02\x03\x04")
            self.assertEqual(evolve.read_urandom(4, p), b"\x01\x02\x03\x04")
            self.assertEqual(len(evolve.read_urandom(16, Path(td) / "missing")), 16)

    def test_write_entropy(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ent"
            evolve.write_entropy(p, b"abcd")
            self.assertEqual(p.read_bytes(), b"abcd")


    def test_novelty(self):
        near = list(evolve.DEFAULTS)
        far = [80.0, 3.0, 0.35, 0.15, 0.60, 1.50, 0.98, 0.70]
        mem = [list(evolve.DEFAULTS)]
        self.assertLess(evolve.novelty(near, mem), 0.05)
        self.assertGreater(evolve.novelty(far, mem), 0.3)
        self.assertEqual(evolve.novelty(far, []), 1.0)

    def test_evolve_with_novelty_memory(self):
        rng = random.Random(9)
        pop = [evolve.random_genome(rng) for _ in range(10)]
        feat = {"flatness": 0.5, "centroid": 0.5, "energy": 0.5, "conf": 0.5}
        mem = [list(evolve.DEFAULTS)]
        best, newpop = evolve.evolve(pop, feat, rng, None, mem)
        self.assertEqual(len(newpop), 10)
        self.assertIn(best, pop)


    def test_prior_mapping_and_fit(self):
        prior = {"count": 20, "edge_density": 0.6, "symmetry": 0.8,
                 "contrast": 0.5, "saturation": 0.4, "value": 0.6}
        g = evolve.prior_genome_from(prior)
        self.assertEqual(len(g), 8)
        for v, (lo, hi) in zip(g, evolve.BOUNDS):
            self.assertGreaterEqual(v, lo)
            self.assertLessEqual(v, hi)
        self.assertAlmostEqual(evolve.prior_fit(g, g), 1.0)
        far = [80.0, 3.0, 0.35, 0.15, 0.60, 1.50, 0.98, 0.70]
        self.assertLess(evolve.prior_fit(far, g), 0.8)

    def test_load_prior(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prior.json"
            self.assertIsNone(evolve.load_prior(p))
            p.write_text('{"count": 3, "edge_density": 0.3}')
            self.assertEqual(evolve.load_prior(p)["count"], 3)

    def test_random_genome_prior_is_near_target(self):
        rng = random.Random(3)
        target = list(evolve.DEFAULTS)
        g = evolve.random_genome(rng, target)
        self.assertGreater(evolve.prior_fit(g, target), 0.5)


    def test_bands8(self):
        f = evolve.features_from_bytes(bytes([255]) * 36)
        self.assertEqual(len(f["bands8"]), 8)
        for v in f["bands8"]:
            self.assertAlmostEqual(v, 1.0, delta=0.02)

    def test_spectral_fit(self):
        g = list(evolve.DEFAULTS)
        f = {"bands8": evolve.descriptor(g)}
        self.assertAlmostEqual(evolve.spectral_fit(g, f), 1.0, places=4)
        wrong = {"bands8": [0.0] * 8}
        self.assertLess(evolve.spectral_fit(g, wrong), 0.6)
        self.assertEqual(evolve.spectral_fit(g, {}), 0.0)

    def test_kernel_is_music_conditioned(self):
        g_a = list(evolve.DEFAULTS)
        g_b = [80.0, 3.0, 0.35, 0.15, 0.60, 1.50, 0.98, 0.70]
        f_a = {"flatness": 0.9, "centroid": 0.8, "energy": 0.5, "conf": 0.7,
               "bands8": [0.9] * 8}
        f_b = {"flatness": 0.1, "centroid": 0.2, "energy": 0.2, "conf": 0.2,
               "bands8": [0.1] * 8}
        m = evolve.PreferenceModel(samples=[(g_a, f_a, 1.0), (g_b, f_b, 0.0)])
        self.assertGreater(m.kernel(g_a, f_a), 0.8)
        self.assertLessEqual(m.kernel(g_a, f_b), 0.5)

    def test_samples_persist(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            m = evolve.PreferenceModel()
            m.update(evolve.DEFAULTS, {"bands8": [0.5] * 8}, 1)
            m.save(p)
            m2 = evolve.PreferenceModel.load(p)
            self.assertEqual(len(m2.samples), 1)
            self.assertGreater(m2.kernel(evolve.DEFAULTS, {"bands8": [0.5] * 8}), 0.8)


class TestComplexity(unittest.TestCase):
    SPARSE = [80.0, 3.0, 0.35, 0.15, 0.60, 0.40, 0.65, 0.00]
    DENSE = [420.0, 10.0, 0.90, 1.00, 1.80, 1.40, 0.90, 0.50]

    def test_complexity_orders(self):
        self.assertGreater(evolve.formation_complexity(self.DENSE),
                           evolve.formation_complexity(self.SPARSE))
        self.assertGreater(evolve.formation_complexity(self.DENSE), 0.8)

    def test_repair_pulls_inside_fence(self):
        out = evolve.repair_genome(self.DENSE, 0.70)
        self.assertLessEqual(evolve.formation_complexity(out), 0.70 + 1e-6)
        for v, (lo, hi) in zip(out, evolve.BOUNDS):
            self.assertGreaterEqual(v, lo)
            self.assertLessEqual(v, hi)

    def test_fence_penalty_lowers_fitness(self):
        f = {"flatness": 0.5, "centroid": 0.5, "energy": 0.5, "conf": 0.5,
             "bands8": [0.5] * 8}
        free = evolve.fitness_with_model(self.DENSE, f)
        fenced = evolve.fitness_with_model(self.DENSE, f, fence=0.50)
        self.assertLess(fenced, free)


if __name__ == "__main__":
    unittest.main()
