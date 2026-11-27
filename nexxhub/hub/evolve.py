"""Genetic algorithm for nexxvis visual variation, with online preference learning.

Reads a compact live-audio feature blob written by nexxvis
(`/run/nexxbeat/spectrum`: 32 u8 log-spectrum bands + 4 u8 levels) and evolves
eight visual parameters toward the current music's character. The fittest
genome is written to `/run/nexxbeat/genome`, which nexxvis reads as uniforms.

Two objectives are combined:

* a designed heuristic (flatness, centroid, energy, beat confidence), and
* a **learned preference**: an online logistic model over the genome + audio
  features, trained from Like/Dislike feedback written by the web UI to
  `/run/nexxbeat/feedback`. The more feedback it gets, the more weight the
  learned model carries (up to 60 %). The model persists in
  `/var/lib/nexxhub/evolve-model.json`, so learning survives restarts.

Exploration: every few generations (while the model is still young) the
service displays a random genome instead of the predicted best, so feedback
covers new regions; the population also gets one random immigrant per
generation. That is the self-optimising loop: feedback -> model -> fitness ->
next generation.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from pathlib import Path

# bar density, Y bands, lens taper, glow, intensity, colour mix, Z scale, bend
BOUNDS = [
    (80.0, 420.0),
    (3.0, 12.0),
    (0.35, 0.95),
    (0.15, 1.20),
    (0.60, 2.00),
    (0.40, 1.50),
    (0.65, 0.98),
    (0.00, 0.70),
]
POP = 16
ELITE = 2
GENERATION_S = 15.0
MUT_P = 0.30
DEFAULTS = [420.0, 6.0, 0.66, 0.90, 1.35, 1.10, 0.82, 0.35]
N_FEATURES = 13  # 8 genome + 4 audio + bias
NOVELTY_K = 5
PRIOR_DEFAULT = "/var/lib/nexxhub/template-prior.json"
COMPLEXITY_FENCE = 0.80


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def formation_complexity(g: list[float]) -> float:
    """Normalised element budget of the rendered formation (0..1).

    Mirrors the crop-genesis grammar: ring count from density, rotational
    symmetry from bands, checker resolution from colour.  This is a
    phenotype measure, not a genome norm — the fence caps what is drawn.
    """
    dens, bands, taper, glow, intensity, color, z, bend = g
    rings = 2.0 + float(math.floor(min(2.9, max(0.0, (dens / 120.0) * 1.8))))
    n = 3.0 if bands < 6.0 else (5.0 if bands < 9.0 else 8.0)
    cells = 34.0 if color > 0.75 else 21.0
    return 0.70 * (rings * n) / 32.0 + 0.30 * (cells / 34.0)


def repair_genome(g: list[float], fence: float) -> list[float]:
    """Pull a genome back inside the complexity fence by thinning elements."""
    out = list(g)
    for _ in range(10):
        if formation_complexity(out) <= fence:
            break
        out[0] = clamp(out[0] * 0.90, *BOUNDS[0])   # fewer rings
        if formation_complexity(out) <= fence:
            break
        out[1] = clamp(out[1] - 0.7, *BOUNDS[1])    # lower symmetry
        if formation_complexity(out) <= fence:
            break
        out[5] = clamp(out[5] - 0.15, *BOUNDS[5])   # coarser checker
    return out


def random_genome(rng: random.Random, prior: list[float] | None = None) -> list[float]:
    if prior and len(prior) == len(BOUNDS):
        return [clamp(t + rng.gauss(0.0, 0.12 * (hi - lo)), lo, hi)
                for t, (lo, hi) in zip(prior, BOUNDS)]
    return [rng.uniform(lo, hi) for lo, hi in BOUNDS]


def mutate(g: list[float], rng: random.Random) -> list[float]:
    out = []
    for v, (lo, hi) in zip(g, BOUNDS):
        if rng.random() < MUT_P:
            v += rng.gauss(0.0, 0.08 * (hi - lo))
        out.append(clamp(v, lo, hi))
    return out


def crossover(a: list[float], b: list[float], rng: random.Random) -> list[float]:
    return [x if rng.random() < 0.5 else y for x, y in zip(a, b)]


def fitness(g: list[float], f: dict) -> float:
    d, b, t, gl, i, c, z, bend = g
    targets = [
        (d / 420.0, 0.35 + 0.65 * f["flatness"]),
        (b / 12.0, 0.25 + 0.75 * f["conf"]),
        (t, 0.40 + 0.45 * f["centroid"]),
        (gl, 0.25 + 0.65 * f["energy"]),
        (i / 2.0, 0.30 + 0.50 * f["energy"]),
        (c / 1.5, 0.35 + 0.55 * f["centroid"]),
        (z, 0.85),
        (bend, 0.10 + 0.45 * f["conf"]),
    ]
    return sum(max(0.0, 1.0 - abs(a - b)) for a, b in targets) / len(targets)


class PreferenceModel:
    """Online logistic regression + a music-conditioned kernel memory.

    The logistic part learns genome->liking.  The kernel part keeps the raw
    feedback samples and weights them by *both* genome similarity and music
    similarity (:meth:`audio_vec`), so a click on a bass-heavy track teaches
    more about bass-heavy music than about a treble-heavy one.
    """

    def __init__(self, weights: list[float] | None = None, n: int = 0,
                 lr: float = 0.20, samples: list | None = None):
        self.w = list(weights) if weights and len(weights) == N_FEATURES else [0.0] * N_FEATURES
        self.n = int(n)
        self.lr = lr
        self.samples = list(samples or [])[-160:]

    def features(self, genome: list[float], f: dict) -> list[float]:
        x = [(v - lo) / (hi - lo) * 2.0 - 1.0 for v, (lo, hi) in zip(genome, BOUNDS)]
        x += [float(f.get("flatness", 0.0)), float(f.get("centroid", 0.0)),
              float(f.get("energy", 0.0)), float(f.get("conf", 0.0)), 1.0]
        return x

    @staticmethod
    def audio_vec(f: dict) -> list[float]:
        b = [float(x) for x in (f.get("bands8") or [])[:8]]
        b += [0.0] * (8 - len(b))
        return [float(f.get(k, 0.0))
                for k in ("flatness", "centroid", "energy", "conf")] + b

    def kernel(self, genome: list[float], f: dict) -> float:
        if not self.samples:
            return 0.5
        gd = descriptor(genome)
        ad = self.audio_vec(f)
        num = den = 0.0
        for gs, fs, y in self.samples:
            dg = sum((a - b) ** 2 for a, b in zip(gd, descriptor(gs)))
            da = sum((a - b) ** 2 for a, b in zip(ad, self.audio_vec(fs)))
            w = math.exp(-dg / 0.06) * math.exp(-da / 0.12)
            num += w * y
            den += w
        return num / den if den > 1e-9 else 0.5

    def predict(self, genome: list[float], f: dict) -> float:
        z = sum(w * xi for w, xi in zip(self.w, self.features(genome, f)))
        z = max(-30.0, min(30.0, z))
        p = 1.0 / (1.0 + math.exp(-z))
        if len(self.samples) >= 6:
            return 0.55 * p + 0.45 * self.kernel(genome, f)
        return p

    def update(self, genome: list[float], f: dict, reward: int) -> None:
        y = 1.0 if reward > 0 else 0.0
        p = self.predict(genome, f)
        g = y - p
        x = self.features(genome, f)
        self.w = [max(-6.0, min(6.0, w + self.lr * g * xi))
                  for w, xi in zip(self.w, x)]
        self.n += 1
        self.samples.append(([float(v) for v in genome], dict(f), y))
        if len(self.samples) > 160:
            self.samples.pop(0)

    def to_dict(self) -> dict:
        return {"weights": self.w, "n": self.n, "samples": self.samples}

    @classmethod
    def from_dict(cls, obj: dict) -> "PreferenceModel":
        samples = []
        for s in obj.get("samples", []) or []:
            try:
                g, f, y = s
                if len(g) == len(BOUNDS) and isinstance(f, dict):
                    samples.append(([float(v) for v in g], f, float(y)))
            except (TypeError, ValueError):
                continue
        return cls(obj.get("weights"), int(obj.get("n", 0)), samples=samples)

    def save(self, path: str | Path) -> None:
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(self.to_dict()) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str | Path) -> "PreferenceModel":
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except (OSError, ValueError, TypeError):
            return cls()


def descriptor(g: list[float]) -> list[float]:
    return [(v - lo) / (hi - lo) for v, (lo, hi) in zip(g, BOUNDS)]


def novelty(g: list[float], memory: list[list[float]]) -> float:
    """Mean distance to the k nearest genomes in recent memory (0..~1.7)."""
    if not memory:
        return 1.0
    d = descriptor(g)
    dists = sorted(sum((a - b) ** 2 for a, b in zip(d, descriptor(m))) ** 0.5
                   for m in memory)
    k = min(NOVELTY_K, len(dists))
    return sum(dists[:k]) / k


def load_prior(path: str | Path) -> dict | None:
    try:
        obj = json.loads(Path(path).read_text())
        return obj if isinstance(obj, dict) and obj.get("count", 0) > 0 else None
    except (OSError, ValueError):
        return None


def prior_genome_from(prior: dict) -> list[float]:
    """Map the image statistics onto the eight genes (within BOUNDS)."""
    e = clamp(float(prior.get("edge_density", 0.2)), 0.0, 1.0)
    s = clamp(float(prior.get("symmetry", 0.5)), 0.0, 1.0)
    c = clamp(float(prior.get("contrast", 0.5)), 0.0, 1.0)
    sa = clamp(float(prior.get("saturation", 0.4)), 0.0, 1.0)
    v = clamp(float(prior.get("value", 0.5)), 0.0, 1.0)
    return [
        80.0 + 340.0 * e,          # density: busy formations
        3.0 + 9.0 * s,             # bands: symmetry
        0.35 + 0.55 * c,           # taper: contrast
        0.15 + 1.00 * v,           # glow: brightness
        0.60 + 1.30 * sa,          # intensity: saturation
        0.40 + 1.00 * sa,          # colour: saturation
        0.65 + 0.30 * (1.0 - 0.5 * c),   # z: scale
        0.00 + 0.60 * c,           # bend: contrast
    ]


def prior_fit(g: list[float], prior: list[float] | None) -> float:
    if not prior or len(prior) != len(BOUNDS):
        return 0.0
    d = 0.0
    for v, t, (lo, hi) in zip(g, prior, BOUNDS):
        d += abs((v - t) / (hi - lo))
    return max(0.0, 1.0 - d / len(BOUNDS))


def spectral_fit(g: list[float], f: dict) -> float:
    """How closely the genome's parameter profile mirrors the 8-band
    spectrum: the music itself supplies the target, no feedback needed."""
    b = f.get("bands8") or []
    if len(b) < 8:
        return 0.0
    d = descriptor(g)
    return max(0.0, 1.0 - sum(abs(a - float(bb)) for a, bb in zip(d, b)) / 8.0)


def fitness_with_model(g: list[float], f: dict,
                       model: PreferenceModel | None = None,
                       memory: list[list[float]] | None = None,
                       prior: list[float] | None = None,
                       fence: float | None = None) -> float:
    h = fitness(g, f)
    if model is not None and model.n > 0:
        lam = min(0.60, 0.06 * model.n)
        h = (1.0 - lam) * h + lam * model.predict(g, f)
    if memory:
        h = 0.80 * h + 0.20 * novelty(g, memory)
    if prior:
        h = 0.85 * h + 0.15 * prior_fit(g, prior)
    if f.get("bands8"):
        h = 0.85 * h + 0.15 * spectral_fit(g, f)
    if fence is not None:
        over = max(0.0, formation_complexity(g) - fence)
        h *= 1.0 - 0.60 * min(over, 0.5)
    return h


def evolve(pop: list[list[float]], f: dict, rng: random.Random,
           model: PreferenceModel | None = None,
           memory: list[list[float]] | None = None,
           prior: list[float] | None = None,
           fence: float | None = None):
    ranked = sorted(pop, key=lambda g: fitness_with_model(g, f, model, memory, prior, fence),
                    reverse=True)
    best = ranked[0]
    newpop = [list(g) for g in ranked[:ELITE]]
    while len(newpop) < len(pop) - 1:
        a = ranked[rng.randrange(len(ranked))]
        b = ranked[rng.randrange(len(ranked))]
        child = mutate(crossover(a, b, rng), rng)
        newpop.append(repair_genome(child, fence) if fence is not None else child)
    if len(newpop) < len(pop):
        imm = random_genome(rng, prior)
        newpop.append(repair_genome(imm, fence) if fence is not None else imm)
    return best, newpop


def features_from_bytes(data: bytes) -> dict:
    if len(data) < 36:
        data = (data + bytes(36))[:36]
    bands = list(data[:32])
    levels = list(data[32:36])
    total = sum(bands)
    n = len(bands)
    energy = total / (255.0 * n)
    centroid = (sum(i * v for i, v in enumerate(bands)) / total / (n - 1)) if total else 0.0
    if total and all(b > 0 for b in bands):
        gm = math.exp(sum(math.log(b) for b in bands) / n)
        am = total / n
        flatness = gm / am if am else 0.0
    else:
        flatness = 0.0
    conf = levels[3] / 255.0
    bands8 = [sum(bands[i:i + 4]) / (4.0 * 255.0) for i in range(0, 32, 4)]
    return {"energy": energy, "centroid": centroid, "flatness": flatness,
            "conf": conf, "bands8": bands8}


def read_features(path: str | Path) -> dict:
    try:
        data = Path(path).read_bytes()
    except OSError:
        data = b""
    return features_from_bytes(data)


def write_genome(path: str | Path, g: list[float]) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(" ".join(f"{v:.4f}" for v in g) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def read_urandom(n: int = 16, path: str | Path = "/dev/urandom") -> bytes:
    """Read fresh entropy from /dev/urandom (fallback: os.urandom)."""
    try:
        with open(path, "rb") as f:
            data = f.read(n)
        if len(data) == n:
            return data
    except OSError:
        pass
    return os.urandom(n)


def write_entropy(path: str | Path, data: bytes) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def parse_feedback(line: str):
    """Return (genome, features, reward) from a feedback JSON line, or None."""
    try:
        obj = json.loads(line)
        g = [float(x) for x in obj["genome"]]
        r = int(obj["reward"])
    except (ValueError, TypeError, KeyError):
        return None
    if len(g) != 8 or r not in (1, -1):
        return None
    raw = obj.get("features") or {}
    f = {k: float(raw.get(k, 0.0))
         for k in ("flatness", "centroid", "energy", "conf")}
    b8 = raw.get("bands8")
    if isinstance(b8, list) and len(b8) >= 8:
        f["bands8"] = [float(x) for x in b8[:8]]
    return g, f, r


def read_new_feedback(path: str | Path, offset: int) -> tuple[list[str], int]:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return [], offset
    if offset > len(data):
        offset = 0
    chunk = data[offset:]
    return chunk.decode("utf-8", "replace").splitlines(), len(data)


def train_feedback(model: PreferenceModel, lines: list[str]) -> int:
    used = 0
    for line in lines:
        parsed = parse_feedback(line)
        if parsed is None:
            continue
        g, f, r = parsed
        model.update(g, f, r)
        used += 1
    return used


def main() -> None:
    spec = Path(os.environ.get("NB_SPECTRUM", "/run/nexxbeat/spectrum"))
    out = Path(os.environ.get("NB_GENOME", "/run/nexxbeat/genome"))
    fb = Path(os.environ.get("NB_FEEDBACK", "/run/nexxbeat/feedback"))
    entropy_path = Path(os.environ.get("NB_ENTROPY", "/run/nexxbeat/entropy"))
    model_path = Path(os.environ.get("NB_MODEL", "/var/lib/nexxhub/evolve-model.json"))
    prior_path = Path(os.environ.get("NB_TEMPLATE_PRIOR", PRIOR_DEFAULT))

    raw_prior = load_prior(prior_path)
    prior = prior_genome_from(raw_prior) if raw_prior else None
    fence = clamp(float(os.environ.get("NB_COMPLEXITY_FENCE", str(COMPLEXITY_FENCE))),
                  0.2, 1.5)
    if raw_prior:
        print(f"evolve: template prior n {raw_prior.get('count', 0)} "
              f"edge {raw_prior.get('edge_density', 0):.2f} "
              f"sym {raw_prior.get('symmetry', 0):.2f} "
              f"con {raw_prior.get('contrast', 0):.2f}", flush=True)
    print(f"evolve: complexity fence {fence:.2f}", flush=True)

    seed = read_urandom(16)
    rng = random.Random(int.from_bytes(seed, "big"))
    try:
        write_entropy(entropy_path, seed)
    except OSError:
        pass

    model = PreferenceModel.load(model_path)
    offset = fb.stat().st_size if (model.n > 0 and fb.exists()) else 0
    if offset:
        # persisted model: skip old feedback; otherwise replay it to learn
        pass
    else:
        lines, offset = read_new_feedback(fb, 0)
        train_feedback(model, lines)

    pop = [repair_genome(random_genome(rng, prior), fence) for _ in range(POP)]
    f = read_features(spec)
    memory: list[list[float]] = []
    best, pop = evolve(pop, f, rng, model, memory, prior, fence)
    write_genome(out, best)
    print(f"evolve: initial fitness {fitness_with_model(best, f, model, memory, prior, fence):.3f} "
          f"pref {model.predict(best, f):.3f} pri {prior_fit(best, prior):.3f} "
          f"spec {spectral_fit(best, f):.3f} cx {formation_complexity(best):.2f} "
          f"n {model.n}", flush=True)

    gen = 0
    while True:
        time.sleep(GENERATION_S)
        f = read_features(spec)

        lines, offset = read_new_feedback(fb, offset)
        used = train_feedback(model, lines)
        if used:
            model.save(model_path)

        # fresh entropy every generation: reseed the GA and publish a blob
        seed = read_urandom(16)
        rng.seed(int.from_bytes(seed, "big"))
        try:
            write_entropy(entropy_path, seed)
        except OSError:
            pass

        best, pop = evolve(pop, f, rng, model, memory, prior, fence)
        gen += 1
        # exploration: show a fresh genome now and then while learning
        explore = (model.n < 40 and gen % 5 == 0 and rng.random() < 0.5)
        shown = repair_genome(random_genome(rng, prior), fence) if explore else best
        nov = novelty(best, memory)
        memory.append(list(shown))
        if len(memory) > 32:
            memory.pop(0)
        write_genome(out, shown)
        print(
            f"evolve: gen {gen} fitness {fitness_with_model(best, f, model, memory, prior, fence):.3f} "
            f"pref {model.predict(best, f):.3f} nov {nov:.3f} "
            f"pri {prior_fit(best, prior):.3f} spec {spectral_fit(best, f):.3f} "
            f"cx {formation_complexity(best):.2f} f {fence:.2f} "
            f"n {model.n} "
            f"fb {used} ent {seed[:4].hex()} {'explore' if explore else 'best'} "
            f"energy {f['energy']:.2f} flat {f['flatness']:.2f} "
            f"centroid {f['centroid']:.2f} conf {f['conf']:.2f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
