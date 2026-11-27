"""Narrative controller for the visualizer.

The story is a thirteen-chapter arc in dimensionality:

    1  seed       single lines / minimal geometry
    2  field      the crop formation
    3  bloom      3-D lift + vortex math
    4  tesseract  4-D projection, full vortex
    5  penteract  5-D lift + pentagram (the Five Seals)
    6  hexeract   6-D lift + Seal of Solomon hexagram
    7  heptad     7-D lift, all seven seals open
    8  ogdoad     8-D rose (eight petals)
    9  ennead     9-D rose
   10  decad      10-D rose
   11  hendecad   11-D rose
   12  dodecad    12-D rose
   13  pleroma    13-D rose, halo

The optional prime ladder (NB_STORY_PRIMES=1, NB_STORY_START=13) makes the
story chase the primes instead: 13 -> 17 -> 19 -> ... -> 97, descending the
same way, so the rose's petal count is always prime.

It advances on its own: a chapter can rise when the music delivers a drop
(an energy jump) or stays energetic past a minimum time, and falls back to
a lower dimension after a long quiet passage.  Every transition glides the
published dimension over ~1 s; there is no break/reassembly.  The state is
published as four floats:

    dim brk seal energy      ->  /run/nexxbeat/story

nexxvis reads it as iStory (dimension, transition, seal index, energy).
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from evolve import read_features


PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
          53, 59, 61, 67, 71, 73, 79, 83, 89, 97)


class Story:
    def __init__(self, primes: bool = False, start: int = 1) -> None:
        self.primes = primes
        self.max = PRIMES[-1] if primes else 13
        self.dim = start if (primes and start in PRIMES) else 1
        self.t_ch = 0.0
        self.brk = 0.0
        self.prev_e = 0.0
        self.cooldown = 0.0
        self.events = 0
        self.seal = 0
        if primes and start >= 13:
            # the chase starts mid-ladder: by the sixth prime every seal is open
            self.events = 6
            self.seal = 6
        self.dim_v = float(self.dim)

    def _step(self, up: bool) -> int:
        """Next dimension: +1/-1 normally, the next/previous prime in prime
        mode, so the story chases 13 -> 17 -> 19 and descends the same way."""
        if not self.primes:
            return self.dim + 1 if up else max(1, self.dim - 1)
        if up:
            for p in PRIMES:
                if p > self.dim:
                    return p
            return self.dim
        prev = 1
        for p in PRIMES:
            if p >= self.dim:
                return prev
            prev = p
        return prev

    def update(self, f: dict, dt: float) -> dict:
        e = max(0.0, min(1.0, float(f.get("energy", 0.0))))
        self.t_ch += dt
        self.cooldown = max(0.0, self.cooldown - dt)
        self.brk = max(0.0, self.brk - dt / 3.0)
        drop = e - self.prev_e

        up_ok = drop > 0.18 or (e > 0.45 and self.t_ch > 32.0)
        if self.primes and e > 0.12 and self.t_ch > 26.0:
            # the chase keeps moving on ordinary music; silence still retreats
            up_ok = True
        if (self.dim < self.max and self.cooldown <= 0.0 and self.t_ch > 18.0
                and up_ok):
            self.dim = self._step(True)
            self.t_ch = 0.0
            self.cooldown = 6.0
            self.events += 1
            self.seal = min(self.events, 6)
        if (self.dim > 1 and self.cooldown <= 0.0 and self.t_ch > 10.0
                and e < 0.12):
            self.dim = self._step(False)
            self.t_ch = 0.0
            self.cooldown = 6.0
            self.events += 1
            self.seal = min(self.events, 6)
        self.dim_v += (self.dim - self.dim_v) * (1.0 - math.exp(-dt / 0.35))
        self.prev_e = e
        return {"dim": self.dim, "dim_v": self.dim_v, "brk": self.brk,
                "seal": self.seal, "energy": e}

    def line(self, st: dict) -> str:
        return (f"{st['dim_v']:.3f} {st['brk']:.3f} {st['seal']} "
                f"{st['energy']:.3f} {st['dim']}\n")


def apply_fixed(st: dict, fixed: int) -> dict:
    """Pin the published dimension when NB_STORY_DIM is set."""
    if fixed <= 0:
        return st
    st = dict(st)
    st["dim"] = max(1, min(97, fixed))
    st["dim_v"] = float(st["dim"])
    st["brk"] = 0.0
    st["seal"] = 6
    return st


def main() -> None:
    spec = Path(os.environ.get("NB_SPECTRUM", "/run/nexxbeat/spectrum"))
    out = Path(os.environ.get("NB_STORY", "/run/nexxbeat/story"))
    try:
        fixed = int(os.environ.get("NB_STORY_DIM", "0") or "0")
    except ValueError:
        fixed = 0
    try:
        start = int(os.environ.get("NB_STORY_START", "1") or "1")
    except ValueError:
        start = 1
    primes = os.environ.get("NB_STORY_PRIMES", "") not in ("", "0")
    story = Story(primes=primes, start=start)
    last = -1
    print("story: listening", flush=True)
    while True:
        f = read_features(spec)
        st = apply_fixed(story.update(f, 0.1), fixed)
        tmp = Path(str(out) + ".tmp")
        try:
            tmp.write_text(story.line(st))
            os.chmod(tmp, 0o644)
            os.replace(tmp, out)
        except OSError:
            pass
        if st["dim"] != last:
            print(f"story: chapter {st['dim']} energy {st['energy']:.2f} "
                  f"events {story.events}", flush=True)
            last = st["dim"]
        time.sleep(0.1)


if __name__ == "__main__":
    main()
