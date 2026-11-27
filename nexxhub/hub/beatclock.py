"""Beat clock from the OPUS-QUAD's undocumented status counter.

The daemon feeds one observation per status packet (~5.86 Hz per deck).  The
counter increments exactly once per beat, so unwrapping it gives an unbounded
beat index.  The true beat happened somewhere in (previous status, this
status]; the 10th percentile of the residuals is a robust estimate of the
earliest arrival and therefore of the beat phase.
"""

from __future__ import annotations

import math
from collections import deque


def _percentile(values, q: float) -> float:
    s = sorted(values)
    if not s:
        raise ValueError("empty sample")
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


class BeatClock:
    """Counter unwrap + min-residual phase estimator."""

    FREE_RUN_AFTER = 2.0
    FREE_RUN_CONFIDENCE = 0.30

    def __init__(self, window: int = 24):
        self.window = window
        self.period = 0.0
        self.reset()

    def reset(self) -> None:
        self._r: deque[float] = deque(maxlen=self.window)
        self._anchor: float | None = None
        self._k = 0
        self._prev: int | None = None
        self._last_increment_t: float | None = None
        self.playing = False
        self._free = False

    def _update_free(self, t: float) -> None:
        if self._last_increment_t is None:
            return
        if t - self._last_increment_t >= self.FREE_RUN_AFTER and self.period > 0:
            if self._anchor is None:
                # BPM-only fallback: with no beat observation yet, assume a
                # beat at the first status packet and free-run from there.
                self._anchor = self._last_increment_t
            self._free = True

    def update(self, t: float, counter: int, period_s: float, playing: bool) -> int:
        """Feed one status observation; return the number of beats advanced."""
        old_period = self.period
        self.period = float(period_s)
        self.playing = bool(playing)
        if old_period > 0.0 and self.period > 0.0 and \
                abs(self.period - old_period) / old_period > 0.005:
            # A real tempo change invalidates residuals measured against the
            # old period; re-anchor on the new grid instead of carrying a
            # ~100 ms phase error for the next 8 s.
            self._r.clear()
            self._anchor = None
            self._free = False
        if not playing:
            self._free = False
            return 0

        if self._prev is None:
            self._prev = counter
            self._last_increment_t = t
            return 0

        delta = (counter - self._prev) & 0xFFFF
        if delta > 32768:
            delta -= 65536

        if delta == 0:
            self._update_free(t)
            return 0

        if delta < 0 or delta > 16:
            # Track change, loop jump or a corrupt counter: re-anchor on the
            # next increment instead of emitting a burst of fake beats.
            self.reset()
            self.playing = bool(playing)
            self._prev = counter
            self._last_increment_t = t
            self._free = False
            return 0

        self._prev = counter
        self._k += delta
        if self.period > 0:
            self._r.append(t - self._k * self.period)
            self._anchor = _percentile(self._r, 0.10)
        self._last_increment_t = t
        self._free = False
        return delta

    def next_beat(self, t: float) -> float | None:
        if not self.playing or self._anchor is None or self.period <= 0:
            return None
        if len(self._r) < 3 and not (self._free and self._anchor is not None):
            return None
        return self._anchor + math.ceil((t - self._anchor) / self.period) * self.period

    def phase(self, t: float) -> float:
        if self._anchor is None or self.period <= 0:
            return 0.0
        return ((t - self._anchor) % self.period) / self.period

    @property
    def confidence(self) -> float:
        if not self.playing or self._anchor is None:
            return 0.0
        if self._free:
            return self.FREE_RUN_CONFIDENCE
        if len(self._r) < 3:
            return 0.0
        spread = _percentile(self._r, 0.5) - _percentile(self._r, 0.1)
        return min(1.0, len(self._r) / 12.0) * max(
            0.0, 1.0 - spread / (0.5 * self.period)
        )
