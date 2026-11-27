"""nexxbeatd — OPUS-QUAD Pro DJ Link beat daemon.

Joins the Pro DJ Link network the way rekordbox does, parses the OPUS-QUAD's
0x0a status packets, turns the undocumented 0xa2 beat counter into a
phase-locked beat clock, selects the deck to follow, and publishes
``<run_dir>/beat`` for ``nexxvis``.

State line (8 fields, atomic write at ~30 Hz)::

    <source> <deck_display> <bpm> <phase> <confidence> <playing> <write_mono> <track_id>

source 2 = Pro DJ Link, 0 = idle.  ``phase`` is the fraction of the beat
elapsed at ``write_mono`` (time.monotonic); ``playing`` is the selected deck's
own 0x40 flag, so the 5 s post-stop hold never invents beats.
"""

from __future__ import annotations

import os
import select
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from beatclock import BeatClock
from djl_protocol import (
    ANNOUNCE_PORT,
    STATUS_PORT,
    Metadata,
    Status,
    is_opus_reply,
    keepalive,
    parse_metadata,
    parse_status,
    pitch_percent,
    send_cdj,
)

SOURCE_IDLE = 0
SOURCE_DJ = 2
SELECTION_HOLD_S = 5.0
STATUS_TIMEOUT_S = 1.5


@dataclass
class DeckState:
    deck: int
    status: Status | None = None
    clock: BeatClock = field(default_factory=BeatClock)
    last_t: float = 0.0
    last_playing_t: float | None = None
    art_buffers: dict = field(default_factory=dict)


def select_deck(states: dict[int, DeckState], now: float,
                hold_s: float = SELECTION_HOLD_S) -> int | None:
    """Master+playing, else playing+on-air, else most recent, else 5 s hold."""
    playing = [
        s for s in states.values()
        if s.status is not None and s.status.playing
        and (getattr(s, "last_t", None) is None
             or now - s.last_t <= STATUS_TIMEOUT_S)
    ]
    for s in playing:
        if s.status.master:
            return s.deck
    for s in playing:
        if s.status.on_air:
            return s.deck
    if playing:
        return max(playing, key=lambda s: s.last_playing_t or 0.0).deck
    held = [
        s for s in states.values()
        if s.last_playing_t is not None and now - s.last_playing_t <= hold_s
    ]
    if held:
        return max(held, key=lambda s: s.last_playing_t).deck
    return None


def format_state(source: int, deck_display: int, bpm: float, phase: float,
                 confidence: float, playing: bool, write_mono: float,
                 track_id: int) -> str:
    return (
        f"{source} {deck_display} {bpm:.2f} {phase:.4f} {confidence:.2f} "
        f"{1 if playing else 0} {write_mono:.3f} {track_id}\n"
    )


def write_state_file(path: Path, line: str) -> None:
    """Atomic write: a reader sees either the old or the new complete line."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(line)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet is sent for UDP connect
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()


def _local_mac() -> bytes:
    for name in ("wlan0", "eth0"):
        p = Path("/sys/class/net") / name / "address"
        try:
            return bytes.fromhex(p.read_text().strip().replace(":", ""))
        except (OSError, ValueError):
            continue
    return bytes(6)


class ArtCache:
    """Reassemble 0x56 album-art chunks, keyed by (deck, track id)."""

    PARTIAL_TTL = 10.0
    COMPLETE_MAX = 4

    def __init__(self):
        self._partial: dict[tuple[int, int], dict[int, bytes]] = {}
        self._partial_t: dict[tuple[int, int], float] = {}
        self._complete: dict[tuple[int, int], bytes] = {}
        self._complete_t: dict[tuple[int, int], float] = {}

    def add(self, meta: Metadata, t: float) -> None:
        if meta.count <= 0 or meta.index >= meta.count:
            return
        # A new track on the same deck abandons that deck's old partial art.
        for key in list(self._partial):
            if key[0] == meta.deck and key[1] != meta.track_id:
                self._partial.pop(key, None)
                self._partial_t.pop(key, None)
        key = (meta.deck, meta.track_id)
        buf = self._partial.setdefault(key, {})
        buf[meta.index] = meta.payload
        self._partial_t[key] = t
        if len(buf) >= meta.count and all(i in buf for i in range(meta.count)):
            self._complete[key] = b"".join(buf[i] for i in range(meta.count))
            self._complete_t[key] = t
            del self._partial[key]
            del self._partial_t[key]
            # A new track on one deck must never evict another deck's art.
            for other in list(self._complete):
                if other != key and other[0] == meta.deck:
                    del self._complete[other]
                    del self._complete_t[other]
            while len(self._complete) > self.COMPLETE_MAX:
                oldest = min(self._complete_t, key=self._complete_t.get)
                del self._complete[oldest]
                del self._complete_t[oldest]

    def get(self, deck: int, track_id: int) -> bytes | None:
        return self._complete.get((deck, track_id))

    def discard_deck(self, deck: int, keep_track: int | None = None) -> None:
        for key in list(self._partial):
            if key[0] == deck and key[1] != keep_track:
                self._partial.pop(key, None)
                self._partial_t.pop(key, None)

    def prune(self, t: float) -> None:
        for key, ts in list(self._partial_t.items()):
            if t - ts > self.PARTIAL_TTL:
                self._partial.pop(key, None)
                self._partial_t.pop(key, None)


class CardPublisher:
    """Render ``cdj.rgba`` on change and keep its mtime fresh while playing."""

    HEARTBEAT_S = 2.0

    def __init__(self, run_dir: str | Path, now=time.time, log=None):
        self.path = Path(run_dir) / "cdj.rgba"
        self.now = now
        self.log = log or (lambda msg: None)
        self._key = None

    def update(self, deck_display: int, status: Status, art_jpeg: bytes | None) -> None:
        # Lazy import keeps the daemon importable where Pillow is unavailable.
        from card import (palette_from_jpeg, render_cdj_card, write_palette,
                          write_rgba)

        key = (deck_display, round(status.bpm_eff, 1), bool(status.master), art_jpeg)
        if key == self._key:
            return
        img = render_cdj_card(
            deck_display, status.bpm_eff, pitch_percent(status.pitch_raw),
            status.master, art_jpeg,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        write_rgba(tmp, img)
        os.replace(tmp, self.path)
        self._key = key
        palette = self.path.with_name("palette")
        if art_jpeg:
            pal = palette_from_jpeg(art_jpeg)
            if pal:
                write_palette(palette, pal)
        else:
            try:
                palette.unlink()
            except FileNotFoundError:
                pass

    def heartbeat(self, t: float | None = None) -> None:
        t = self.now() if t is None else t
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return
        if t - st.st_mtime >= self.HEARTBEAT_S:
            os.utime(self.path, (t, t))

    def remove(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        try:
            self.path.with_name("palette").unlink()
        except FileNotFoundError:
            pass
        self._key = None


class BeatDaemon:
    def __init__(self, run_dir: str | Path | None = None,
                 announce_port: int | None = None,
                 status_port: int | None = None,
                 broadcast_addr: str | None = None,
                 client_name: str = "nexxxen",
                 sender=None, log=None, card=None):
        self.run_dir = Path(run_dir or os.environ.get("NB_RUN_DIR", "/run/nexxbeat"))
        self.announce_port = int(announce_port or os.environ.get("NB_ANNOUNCE_PORT", ANNOUNCE_PORT))
        self.status_port = int(status_port or os.environ.get("NB_STATUS_PORT", STATUS_PORT))
        self.broadcast_addr = broadcast_addr or os.environ.get("NB_BROADCAST_ADDR", "255.255.255.255")
        self.client_name = client_name
        self.decks: dict[int, DeckState] = {}
        self.unit_ip: str | None = None
        self.last_status_t: float | None = None
        self.last_handshake_t: float | None = None
        self._send = sender or (lambda payload, addr: None)
        self.log = log or (lambda msg: print(f"nexxbeatd: {msg}", flush=True))
        self._send_err_logged = False
        self._last_selection: tuple[int, int] | None = None
        self.art = ArtCache()
        self.card = card if card is not None else CardPublisher(self.run_dir, log=self.log)
        self._idle_since: float | None = None

    # ----------------------------------------------------------------- data
    def handle_datagram(self, pkt: bytes, src_ip: str, t: float) -> None:
        if is_opus_reply(pkt):
            if self.unit_ip != src_ip:
                what = "joined" if self.unit_ip is None else "unit moved"
                self.log(f"{what} OPUS-QUAD at {src_ip}")
            self.unit_ip = src_ip
            self.send_handshake(t)
            return
        if len(pkt) < 11:
            return
        kind = pkt[10]
        if kind == 0x0A:
            st = parse_status(pkt, t)
            if st is not None:
                self.last_status_t = t
                self.handle_status(st, t)
        elif kind == 0x56:
            meta = parse_metadata(pkt)
            if meta is not None:
                self.handle_metadata(meta, t)

    def handle_status(self, st: Status, t: float) -> None:
        d = self.decks.get(st.deck)
        if d is None:
            d = DeckState(st.deck)
            self.decks[st.deck] = d
            self.log(f"deck {st.deck_display} seen (id {st.deck})")
        if d.status is not None and d.status.track_id != st.track_id:
            d.clock.reset()
            self.art.discard_deck(st.deck, keep_track=st.track_id)
            self.log(f"deck {st.deck_display} track {st.track_id}")
        d.status = st
        d.last_t = t
        period = 60.0 / st.bpm_eff if st.bpm_eff > 0 else 0.0
        d.clock.update(t, st.beat_counter, period,
                       bool(st.playing and st.bpm_eff > 0))
        if st.playing:
            d.last_playing_t = t

    def handle_metadata(self, meta: Metadata, t: float) -> None:
        if meta.subtype == 2:  # JPEG album art
            self.art.add(meta, t)

    def send_handshake(self, t: float) -> None:
        if self.unit_ip is None:
            return
        try:
            self._send(send_cdj(self.client_name), (self.unit_ip, self.status_port))
            self._send_err_logged = False
        except OSError as e:
            # A Wi-Fi drop makes sendto fail; keep the daemon alive and retry.
            if not self._send_err_logged:
                self.log(f"handshake send failed ({e}); retrying")
                self._send_err_logged = True
        self.last_handshake_t = t

    # ----------------------------------------------------------------- state
    def selected_deck(self, t: float) -> int | None:
        """Selection is only valid while its status packets keep arriving."""
        deck_no = select_deck(self.decks, t)
        if deck_no is None:
            return None
        d = self.decks[deck_no]
        if d.status is None or t - d.last_t > STATUS_TIMEOUT_S:
            return None
        return deck_no

    def state_line(self, t: float) -> str:
        deck_no = self.selected_deck(t)
        if deck_no is None:
            # Spec §8.2: the idle line is literal zeros, not 2-dp floats.
            return f"{SOURCE_IDLE} 0 0 0 0 0 {t:.3f} 0\n"
        d = self.decks[deck_no]
        s = d.status
        if s is None:
            return f"{SOURCE_IDLE} 0 0 0 0 0 {t:.3f} 0\n"
        return format_state(
            SOURCE_DJ, s.deck_display, s.bpm_eff, d.clock.phase(t),
            d.clock.confidence, bool(s.playing), t, s.track_id,
        )

    def update_card(self, t: float) -> None:
        """Draw the selected deck's card; heartbeat while playing or held."""
        self.art.prune(t)
        deck_no = self.selected_deck(t)
        if deck_no is None:
            if self._idle_since is None:
                self._idle_since = t
            elif t - self._idle_since > 5.0:
                self.card.remove()
            return
        self._idle_since = None
        d = self.decks[deck_no]
        s = d.status
        if s is None:
            return
        self.card.update(s.deck_display, s, self.art.get(s.deck, s.track_id))
        held = d.last_playing_t is not None and t - d.last_playing_t <= 5.0
        if s.playing or held:
            self.card.heartbeat(time.time())

    def write_state(self, t: float) -> None:
        if not self.run_dir.exists():
            self.run_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.run_dir, 0o755)
        line = self.state_line(t)
        fields = line.split()
        sel = (int(fields[0]), int(fields[1]))
        if sel != self._last_selection:
            self._last_selection = sel
            if sel[0] == SOURCE_IDLE:
                self.log("idle")
            else:
                self.log(f"following deck {sel[1]}")
        write_state_file(self.run_dir / "beat", line)
        self.update_card(t)

    # ----------------------------------------------------------------- loop
    def _drain(self, sock: socket.socket) -> None:
        while True:
            try:
                pkt, addr = sock.recvfrom(4096)
            except (BlockingIOError, socket.timeout):
                return
            except OSError:
                return
            self.handle_datagram(pkt, addr[0], time.monotonic())

    def run(self) -> None:
        ann = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ann.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ann.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        ann.bind(("0.0.0.0", self.announce_port))
        sta = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sta.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sta.bind(("0.0.0.0", self.status_port))
        ann.setblocking(False)
        sta.setblocking(False)
        self._send = lambda payload, addr: sta.sendto(payload, addr)

        ip = _local_ip()
        mac = _local_mac()
        self.log(f"listening {self.announce_port}/{self.status_port} as {ip}")
        next_keepalive = 0.0
        next_write = 0.0
        try:
            while True:
                now = time.monotonic()
                timeout = max(0.0, min(next_write - now, next_keepalive - now, 0.05))
                try:
                    select.select([sta, ann], [], [], timeout)
                except InterruptedError:
                    pass
                now = time.monotonic()
                if now >= next_keepalive:
                    try:
                        ann.sendto(keepalive(mac, ip),
                                   (self.broadcast_addr, self.announce_port))
                    except OSError:
                        pass
                    next_keepalive = now + 2.0
                self._drain(sta)
                self._drain(ann)
                if self.unit_ip is not None:
                    stale = self.last_status_t is None or now - self.last_status_t > 3.0
                    due = self.last_handshake_t is None or now - self.last_handshake_t >= 3.0
                    if stale and due:
                        self.send_handshake(now)
                if now >= next_write:
                    self.write_state(now)
                    next_write = now + 1.0 / 30.0
        finally:
            ann.close()
            sta.close()


def main() -> int:
    daemon = BeatDaemon()
    try:
        daemon.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
