# nexxvis Beat-Reactive Screensaver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tty1 `nexxvis` screensaver beat-locked: Pro DJ Link beats from the OPUS-QUAD over Wi-Fi, PipeWire beat detection as the fallback, and a small CDJ deck/BPM/album-art card.

**Architecture:** A Python daemon (`nexxbeatd`) speaks the OPUS-QUAD's rekordbox-style Pro DJ Link handshake, parses status packets, derives a phase-locked beat clock from the undocumented `0xa2/0xa3` counter, and publishes `/run/nexxbeat/beat` + `cdj.rgba`. `nexxvis` (C/EGL) reads that state, runs its own onset/BPM detector on the existing PipeWire FFT, exposes `iBeat`/`iBPM` to the shaders, and draws the card.

**Tech Stack:** Python 3.13 (stdlib, Pillow), C99/GLES3/EGL/GBM/DRM, GLSL, systemd, Raspberry Pi 4, Raspberry Pi OS (HiFiBerryOS NG).

**Spec:** `/Users/cxfxcxb/nexxxen/docs/superpowers/specs/2026-11-22-nexxvis-beat-reactive-design.md`

## Global Constraints

- Work on the Pi over SSH:
  `ssh -o BatchMode=yes -o UserKnownHostsFile=/Users/cxfxcxb/nexxxen/dsp-tools/known_hosts_nexxxen nexxxen`
- Source of truth: `/home/cxfxcxb/src/nexxhub/`. Installed: `/usr/local/bin/nexxvis`, `/usr/local/share/nexxvis/shaders/`, `/usr/local/lib/nexxhub/`, `/etc/systemd/system/`.
- No new dependencies. Python: stdlib + Pillow (already installed). C: gcc + EGL/GLESv2/GBM/DRM/pthread/math (already installed).
- Live render baseline must be preserved: `NV_MODE=2560x1440@60`, `NV_SCALE=0.375`, `NV_CYCLE=300`, `NV_SINK=speakereq2x2`; `10-aurora.frag` uses `// nv:scale=0.25`. The source tree is stale (`1920x1080@60`, `0.5`, `0.34`) and must be synced first.
- Not a git repo: every task ends with a timestamped snapshot under `~/src/nexxhub/.backup/` (helper `snap.sh`, Task 1), not a git commit.
- Pro DJ Link: UDP 50000 (announce/keep-alive), UDP 50002 (status); 10-byte header `51 73 70 74 31 57 6d 4a 4f 4c`; type at byte `0x0a`.
- Status packet (293 bytes): deck `0x21` (9–12), track ID `0x2c` (u32 BE), pitch `0x8d` (3 B BE, centre `0x100000`), flags `0x89` (`0x40` playing, `0x20` master, `0x08` on-air, `0x10` synced), BPM×100 `0x92` (u16 BE), beat counter `0xa2` (u16 BE), beat-in-bar `0xa6` (unused).
- Metadata `0x56`: deck `0x21`, subtype `0x25` (2 = JPEG art), track ID `0x28` (u32 BE), index `0x31`, count `0x33`, payload `0x34`.
- Files: `/run/nexxbeat/beat` (atomic text, 0644, ~30 Hz), `/run/nexxbeat/cdj.rgba` (Pillow card, 0644). Freshness: beat state < 1.0 s; card mtime < 5 s; status timeout 1.5 s; re-handshake 3 s / 30 s; heartbeat 2 s; idle card removal 5 s; `NV_BEAT_OFFSET_MS` default 0 ms (the spec's `NB_OFFSET_MS` knob; applied in `nexxvis`).
- `playing` = the selected deck's own `0x40` flag, not the daemon's selection hold. The 5 s post-stop hold keeps the deck/card selected but not the beat clock.
- No cloud, no audio capture of the optical input, no DSP/driver changes, no new screen mode. LAN UDP only.
- Do not restart `nexx-visualizer` during install/rollback if another screen mode is active.
- Titles/artist are out of scope for v1 (album art is in scope).

## Review Focus

- **Track change / tempo change / counter reset:** the counter must re-anchor without a burst of fake beats; re-lock within ~2 s. (Tested in Tasks 3, 5, 7.)
- **Wi-Fi drop, OPUS-QUAD IP change, daemon restart:** re-handshake within seconds; the visualizer must keep rendering (fallback), never freeze. (Tasks 5, 7.)
- **Steady track:** the card must not disappear from mtime staleness; the 2 s heartbeat is the fix. (Task 6.)
- **Pause/stop/silence:** no invented pulses; the card may hold 5 s; the visualizer falls back cleanly. (Tasks 5, 6, 7.)
- **Install/rollback while Kodi/Artemis/RetroArch is active:** do not stop the session; restore the shader directory on rollback. (Task 12.)
- **Non-selected deck loads a track while the other plays:** the selected deck's album art must not be overwritten. (Task 6.)

---

### Task 1: Baseline sync, build tooling, snapshot helper

**Files:**
- Create: `~/src/nexxhub/snap.sh`
- Create: `~/src/nexxhub/vis/build.sh`
- Modify: `~/src/nexxhub/units/nexx-visualizer.service`
- Modify: `~/src/nexxhub/vis/shaders/10-aurora.frag`

**Interfaces:**
- Produces: `snap.sh <relative paths...>` → prints the backup directory; `build.sh` → `vis/nexxvis` with the exact live render settings.

- [ ] **Step 1: Verify the live/source drift**

Run on the Pi:
`systemctl cat nexx-visualizer | grep -E "NV_MODE|NV_SCALE"; grep -H "nv:scale" /usr/local/share/nexxvis/shaders/*.frag; grep -E "NV_MODE|NV_SCALE" ~/src/nexxhub/units/nexx-visualizer.service; grep -H "nv:scale" ~/src/nexxhub/vis/shaders/*.frag`
Expected: live `2560x1440@60` / `0.375` / `0.25`; source `1920x1080@60` / `0.5` / `0.34`.

- [ ] **Step 2: Sync the source unit and shader to the live values**

Edit `~/src/nexxhub/units/nexx-visualizer.service`: `NV_MODE=2560x1440@60`, `NV_SCALE=0.375`. Edit `~/src/nexxhub/vis/shaders/10-aurora.frag`: `// nv:scale=0.25`.
Run `diff <(systemctl cat nexx-visualizer | sed '1,2d') ~/src/nexxhub/units/nexx-visualizer.service`
Expected: only the header-comment difference remains.

- [ ] **Step 3: Add the snapshot helper**

Create `~/src/nexxhub/snap.sh`:
```sh
#!/bin/sh
set -eu
ts=$(date +%Y%m%d-%H%M%S); d="$HOME/src/nexxhub/.backup/$ts"; mkdir -p "$d"
for f in "$@"; do mkdir -p "$d/$(dirname "$f")"; cp -a "$HOME/src/nexxhub/$f" "$d/$f"; done
echo "$d"
```
`chmod +x ~/src/nexxhub/snap.sh`.

- [ ] **Step 4: Add the build script**

Create `~/src/nexxhub/vis/build.sh`:
```sh
#!/bin/sh
set -eu
cd "$(dirname "$0")"
gcc -O2 -Wall -Wextra -o nexxvis nexxvis.c -lEGL -lGLESv2 -lgbm -ldrm -lm -lpthread
```
`chmod +x`. Run `./build.sh` and `sha256sum nexxvis`.
Expected: build succeeds; the hash changes or matches depending on the compiler (it is not required to equal the installed binary; the source is unchanged apart from settings).

- [ ] **Step 5: Snapshot and verify**

`~/src/nexxhub/snap.sh units/nexx-visualizer.service vis/shaders/10-aurora.frag vis/build.sh snap.sh`
Expected: prints a timestamped directory; `ls` shows the four files.

---

### Task 2: `djl_protocol.py` — packet layouts and parsers

**Files:**
- Create: `~/src/nexxhub/hub/djl_protocol.py`
- Test: `~/src/nexxhub/hub/test_djl_protocol.py`
- Fixtures: `~/src/nexxhub/hub/fixtures/status9.hex`, `status10.hex`, `art_meta.hex`

**Interfaces:**
- Produces:
  `HEADER: bytes`, `ANNOUNCE_PORT=50000`, `STATUS_PORT=50002`, `OPUS_NAME="OPUS-QUAD"`.
  `keepalive(mac: bytes, ip: str) -> bytes` (54 bytes).
  `send_cdj(client_name: str = "nexxxen") -> bytes` (296 bytes).
  `parse_status(pkt: bytes, t_recv: float) -> Status | None`.
  `parse_metadata(pkt: bytes) -> Metadata | None`.
  `is_opus_reply(pkt: bytes) -> bool` (header + type `0x10` + name `OPUS-QUAD`).
  `translate_deck(n: int) -> int` (9→1 … 12→4, 0→0).
  `pitch_percent(raw: int) -> float`.
  Dataclasses `Status` (deck, deck_display, bpm_raw, pitch_raw, bpm_eff, playing, master, on_air, synced, beat_counter, track_id, firmware, t_recv) and `Metadata` (deck, subtype, track_id, index, count, payload).

- [ ] **Step 1: Create the fixtures (on the Mac, then copy to the Pi)**

Run on the Mac:
```python
import re
rows=[]
for ln in open("/Users/cxfxcxb/nexxxen/nexxbeat-recon/opusq_spike.log"):
    t=ln.strip()
    if t and re.fullmatch(r"[0-9a-f]+", t): rows.append(bytes.fromhex(t))
def save(name,b):
    open(f"/Users/cxfxcxb/nexxxen/nexxhub/hub/fixtures/{name}.hex","w").write(b.hex())
import os; os.makedirs("/Users/cxfxcxb/nexxxen/nexxhub/hub/fixtures", exist_ok=True)
save("status9", [b for b in rows if len(b)>0x100 and b[10]==0x0a and b[0x21]==9][-1])
save("status10", [b for b in rows if len(b)>0x100 and b[10]==0x0a and b[0x21]==10][-1])
save("art_meta", [b for b in rows if len(b)>0x34 and b[10]==0x56 and b[0x25]==2][0])
```
Copy `hub/fixtures/*.hex` to `nexxxen:~/src/nexxhub/hub/fixtures/`.
Expected: `status9.hex` is the last deck-9 packet (counter 560); `art_meta.hex` is deck 10, subtype 2, track 413, index 0, count 6.

- [ ] **Step 2: Write the failing tests**

Create `test_djl_protocol.py` with:
```python
import unittest
from pathlib import Path
from djl_protocol import *

class TestPackets(unittest.TestCase):
    def test_keepalive_layout(self):
        mac = bytes.fromhex("aabbccddeeff"); ip = "<pi-ip>"
        p = keepalive(mac, ip)
        self.assertEqual(len(p), 54)
        self.assertEqual(p[:10], HEADER)
        self.assertEqual(p[10:12], b"\x06\x00")
        self.assertEqual(p[12:32].rstrip(b"\0"), b"rekordbox")
        self.assertEqual(p[32:38], bytes([1,3,0,0x36,0x17,1]))
        self.assertEqual(p[38:44], mac)
        self.assertEqual(p[44:48], bytes([192,168,1,199]))
        self.assertEqual(p[48:54], bytes([4,1,0,0,4,8]))
    def test_send_cdj_layout(self):
        p = send_cdj("nexxxen")
        self.assertEqual(len(p), 10+1+20+10+255)
        self.assertEqual(p[10], 0x11)
        self.assertEqual(p[11:31].rstrip(b"\0"), b"rekordbox")
        self.assertEqual(p[31:41], bytes([1,1,0x17,1,4,0x17,1,0,0,0]))
        self.assertEqual(p[41], ord("n")); self.assertEqual(p[42], 0); self.assertEqual(p[43], ord("e"))
    def test_status_fixture(self):
        b = bytes.fromhex((Path(__file__).parent / "fixtures" / "status9.hex").read_text())
        s = parse_status(b, 100.0)
        self.assertEqual(len(b), 293)
        self.assertEqual(s.deck, 9); self.assertEqual(s.deck_display, 1)
        self.assertEqual(s.bpm_raw, 17400); self.assertEqual(s.pitch_raw, 0x102eb2)
        self.assertAlmostEqual(s.bpm_eff, 176.07, delta=0.02)
        self.assertTrue(s.playing and s.master and s.on_air); self.assertFalse(s.synced)
        self.assertEqual(s.beat_counter, 560); self.assertEqual(s.track_id, 1217)
        self.assertEqual(s.firmware, "1.30")
```
`test_status_rejects_short`: `parse_status(b"\x00"*100, 0.0) is None`. `test_metadata_fixture`: deck 10, subtype 2, track_id 413, index 0, count 6, len 512. `test_translate_deck`: 9→1, 12→4, 0→0. `test_pitch`: 0x100000→0.0, 0x102eb2→1.19. `test_opus_reply`: `is_opus_reply(HEADER + b"\x10" + b"OPUS-QUAD".ljust(20, b"\0") + bytes([1,0,9,0,0]))` is true; a 10-byte prefix is false.

- [ ] **Step 3: Run the tests and verify they fail**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_djl_protocol`
Expected: `ModuleNotFoundError` / `ImportError`.

- [ ] **Step 4: Implement `djl_protocol.py`**

Use `struct.unpack_from(">H", pkt, 0x92)` etc.; clamp `parse_status` to `len(pkt) >= 0xa8` and `pkt[10] == 0x0a`; read the name as `pkt[0x0b:0x1f]`; `bpm_eff = bpm_raw/100 * (1 + pitch_percent(pitch_raw)/100)` when `bpm_raw not in (0, 0xFFFF)`, else `0.0`; flags at `0x89`; `track_id = u32(0x2c)`; `firmware = pkt[0x7c:0x80].decode("ascii","replace")`. `parse_metadata` requires `len >= 0x34` and type `0x56`; `payload = pkt[0x34:]`. `weird(s)` writes the name bytes at even offsets of a 255-byte zero buffer.

- [ ] **Step 5: Run the tests and verify they pass**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_djl_protocol`
Expected: all pass.

- [ ] **Step 6: Snapshot**

`~/src/nexxhub/snap.sh hub/djl_protocol.py hub/test_djl_protocol.py hub/fixtures`

---

### Task 3: `beatclock.py` — counter unwrap and phase estimator

**Files:**
- Create: `~/src/nexxhub/hub/beatclock.py`
- Test: `~/src/nexxhub/hub/test_beatclock.py`

**Interfaces:**
- Produces: `BeatClock(window: int = 24)` with `reset()`, `update(t: float, counter: int, period_s: float, playing: bool) -> int` (beats advanced), `next_beat(t: float) -> float | None`, `phase(t: float) -> float` (0..1), `confidence: float`, `period: float`.

- [ ] **Step 1: Write the failing tests**

Create `test_beatclock.py`:
```python
import random, unittest
from beatclock import BeatClock

class TestBeatClock(unittest.TestCase):
    def test_wrap(self):
        c = BeatClock(); c.update(0.0, 65534, 0.341, True)
        self.assertEqual(c.update(0.34, 65535, 0.341, True), 1)
        self.assertEqual(c.update(0.68, 0, 0.341, True), 1)
    def test_missed(self):
        c = BeatClock(); c.update(0.0, 100, 0.341, True)
        self.assertEqual(c.update(1.0, 103, 0.341, True), 3)
    def test_jitter_phase(self):
        rng = random.Random(7); T = 60/176.0; c = BeatClock(); t = 0.0
        for k in range(1, 30):
            t = k*T + rng.uniform(0.0, 0.1706)
            c.update(t, 1000+k, T, True)
        nxt = c.next_beat(t)
        err = abs(((nxt - 30*T + T/2) % T) - T/2)
        self.assertLess(err, 0.020); self.assertGreater(c.confidence, 0.5)
    def test_pause(self):
        c = BeatClock(); c.update(0.0, 5, 0.341, True)
        c.update(2.0, 5, 0.341, False)
        self.assertIsNone(c.next_beat(2.0)); self.assertEqual(c.confidence, 0.0)
    def test_no_increments_free_runs(self):
        c = BeatClock(); c.update(0.0, 5, 0.341, True)
        c.update(2.0, 5, 0.341, True)
        self.assertIsNotNone(c.next_beat(2.0))
        self.assertGreaterEqual(c.confidence, 0.2); self.assertLessEqual(c.confidence, 0.4)
    def test_track_change_reset(self):
        c = BeatClock(); c.update(0.0, 5000, 0.341, True)
        self.assertEqual(c.update(0.34, 3, 0.341, True), 0)
        self.assertIsNone(c.next_beat(0.34))
        self.assertEqual(c.update(0.68, 4, 0.341, True), 1)
```

- [ ] **Step 2: Run and verify failure**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_beatclock`
Expected: `ImportError`.

- [ ] **Step 3: Implement `BeatClock`**

Algorithm:
- Unwrap: `delta = counter - prev`; if `delta < -32768: delta += 65536`; if `delta == 0`: no beat; if `delta < 0` or `delta > 16`: `reset()` and return 0; else `k += delta`.
- On an increment, append `r = t - k*period` to a deque(maxlen=window).
- `anchor = percentile(r, 0.10)`; `next_beat(t) = anchor + ceil((t-anchor)/period)*period` only when `playing` and `len(r) >= 3`.
- `phase(t) = ((t-anchor) % period)/period`.
- Confidence: `0.0` if not playing; else `min(1, len(r)/12) * max(0, 1 - spread/(0.5*period))` where `spread = p50(r) - p10(r)`; 0.0 if `< 3` observations.
- Track `last_increment_t`. If playing and `t - last_increment_t > 2` with at least one observation, free-run from the last anchor/period with confidence exactly `0.30`; re-anchor on the next increment. If not playing, `next_beat` is `None` and confidence is `0.0`.
- `period` is the value passed to the last `update` (the daemon supplies `60/bpm_eff`); no internal EMA needed in v1 (the spec allows it; keep the test-deterministic behavior).

- [ ] **Step 4: Run and verify pass**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_beatclock`
Expected: pass (the jitter test must be within 20 ms; if not, lower the percentile to 0.05 or raise `window` — record the choice).

- [ ] **Step 5: Snapshot**

`~/src/nexxhub/snap.sh hub/beatclock.py hub/test_beatclock.py`

---

### Task 4: `card.py` — CDJ card renderer

**Files:**
- Create: `~/src/nexxhub/hub/card.py`
- Test: `~/src/nexxhub/hub/test_card.py`

**Interfaces:**
- Produces: `CARD_W=1180`, `CARD_H=300`; `render_cdj_card(deck_display: int, bpm: float, pitch_pct: float, master: bool, art_jpeg: bytes | None) -> PIL.Image.Image`; `write_rgba(path: Path, img) -> None`.

- [ ] **Step 1: Write the failing tests**

`test_card.py`: render with `deck_display=1, bpm=174.0, pitch_pct=1.2, master=True, art_jpeg=None`; assert `(1180,300)`, mode `RGBA`, and at least one pixel with alpha > 0. Render with a 64×64 JPEG made by Pillow in the test; assert no exception and the mode/size. `write_rgba` to a temp path; read back with `struct.unpack("<II", head)`; assert `(1180,300)` and the file length is `8 + 1180*300*4`.

- [ ] **Step 2: Run and verify failure**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_card`
Expected: `ImportError`.

- [ ] **Step 3: Implement `card.py`**

Reuse `nowplaying.py`'s visual language: transparent RGBA, a rounded dark glass panel, DejaVu fonts, a 240×240 art tile (or a music glyph panel), the tag `PRO DJ LINK · DECK {deck_display}`, a `MASTER` badge when true, `f"{bpm:.1f}"` large, `f"{abs(pitch_pct):.1f} %"` with a sign, and a small beat dot. No title/artist. `write_rgba` writes `<II` + RGBA bytes; use a tmp file + `os.replace` in the daemon, not here.

- [ ] **Step 4: Run and verify pass**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_card`
Expected: pass.

- [ ] **Step 5: Snapshot**

`~/src/nexxhub/snap.sh hub/card.py hub/test_card.py`

---

### Task 5: `nexxbeatd.py` — join, per-deck clocks, selection, state file

**Files:**
- Create: `~/src/nexxhub/hub/nexxbeatd.py`
- Test: `~/src/nexxhub/hub/test_nexxbeatd.py`

**Interfaces:**
- Consumes: `djl_protocol.keepalive/send_cdj/parse_status/translate_deck`, `beatclock.BeatClock`, `card.render_cdj_card/write_rgba`.
- Produces: `/run/nexxbeat/beat` line:
  `<source> <deck_display> <bpm> <phase> <confidence> <playing> <write_mono> <track_id>\n`
  (`source` 2 = Pro DJ Link, 0 = idle); `DeckState(deck, status, clock, last_t, last_playing_t, art_buffers)`; `select_deck(states, now, hold_s=5.0) -> int | None`; `format_state(source, deck_display, bpm, phase, confidence, playing, write_mono, track_id) -> str` formatted with `f"{source} {deck} {bpm:.2f} {phase:.4f} {confidence:.2f} {playing} {write_mono:.3f} {track_id}\n"`. The daemon creates `NB_RUN_DIR` (0755) if missing.

- [ ] **Step 1: Write the failing tests**

`test_nexxbeatd.py`:
- `test_select_master`: deck 9 master+playing, deck 10 playing+on-air → 9.
- `test_select_on_air_fallback`: no master; deck 10 playing+on-air, deck 11 playing → 10.
- `test_select_hold`: a deck stopped 2 s ago is selected; 6 s ago → `None`.
- `test_idle_line`: no decks → `"0 0 0 0 0 0 <mono> 0\n"` (parse the fields).
- `test_state_playing`: selected deck playing → source 2, playing 1, bpm/confidence/phase from the clock; pause → playing 0 and the visualizer must not use the DJ clock.
- `test_atomic_state`: write 100 lines in a temp dir while a reader reads; every read parses into 8 fields.
- `test_pitch_and_bpm`: a status fixture feeds the clock; `bpm_eff` is 176.07 ± 0.02.
- `test_opus_ip_learned`: a 36-byte `0x10` packet from address `10.0.0.5` sets `unit_ip`; the next `send_cdj` target is `10.0.0.5` (fake sender records the target). A second `0x10` from `10.0.0.6` updates it (Wi-Fi/DHCP change).

The selection tests use a small `SimpleNamespace` deck state with `status`, `last_playing_t`; the state-line tests call `format_state` directly.

- [ ] **Step 2: Run and verify failure**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_nexxbeatd`
Expected: `ImportError`.

- [ ] **Step 3: Implement the daemon core**

- Sockets: bind `0.0.0.0:${NB_ANNOUNCE_PORT:-50000}` and `0.0.0.0:${NB_STATUS_PORT:-50002}`; `SO_REUSEADDR`, `SO_BROADCAST`; send keep-alive to `${NB_BROADCAST_ADDR:-255.255.255.255}:announce` every 2 s.
- On a `0x10` packet on the status socket: set `unit_ip = addr[0]`, send `send_cdj()` to `unit_ip:status`; resend on start, when no status for 3 s, and every 30 s.
- On `0x0a`: `parse_status`; update that deck's `BeatClock` with `period=60/bpm_eff` (if bpm_eff > 0), `counter`, `playing`; store status; update `last_playing_t`.
- Selection per `select_deck`; state line per `format_state`; write atomically (`tmp` + `os.replace`) at 30 Hz; idle line when no deck.
- The 5 s hold is selection-only; `playing` comes from the selected deck's status.
- Env: `NB_RUN_DIR` (default `/run/nexxbeat`), `NB_ANNOUNCE_PORT`, `NB_STATUS_PORT`, `NB_BROADCAST_ADDR`, `NB_BEAT_LOG`.
- Log state changes only (joined, re-handshake, deck switch, idle).
- Leave the card hooks for Task 6; this task writes only the state file.

- [ ] **Step 4: Run and verify pass**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_nexxbeatd`
Expected: pass.

- [ ] **Step 5: Dry-run the sockets on loopback**

Run `NB_RUN_DIR=/tmp/nb-test NB_ANNOUNCE_PORT=60000 NB_STATUS_PORT=60002 NB_BROADCAST_ADDR=127.0.0.1 python3 nexxbeatd.py` and in another shell `NB_RUN_DIR=/tmp/nb-test ...` no—just check it starts, writes `0 0 0 0 0 0 ... 0`, and stops on SIGTERM. Expected: no exceptions; idle line present.

- [ ] **Step 6: Snapshot**

`~/src/nexxhub/snap.sh hub/nexxbeatd.py hub/test_nexxbeatd.py`

---

### Task 6: Album art reassembly, per-deck cache, card heartbeat

**Files:**
- Modify: `~/src/nexxhub/hub/nexxbeatd.py`
- Test: `~/src/nexxhub/hub/test_nexxbeatd.py` (add cases)
- Test: `~/src/nexxhub/hub/test_card.py` (only if helper functions move)

**Interfaces:**
- Produces: `ArtCache` with `add(meta: Metadata, t: float) -> None`, `get(deck: int, track_id: int) -> bytes | None`, `prune(t: float) -> None`; `CardPublisher(run_dir, now=time.monotonic)` with `update(deck, status, art_jpeg)`, `heartbeat(t)`, `remove()`.

- [ ] **Step 1: Write the failing tests**

Add to `test_nexxbeatd.py`:
- `test_art_reassembly`: three `Metadata` chunks (index 0/1/2, count 3, payloads `a`,`b`,`c`) for deck 9, track 1217 → `get(9,1217) == b"abc"`; incomplete → `None`.
- `test_art_per_deck`: add deck 9/track 1217 art and deck 10/track 413 art; both retrievable; adding deck 10 does not change deck 9.
- `test_art_new_track_discards`: a new track ID on the same deck discards the old buffer; incomplete buffers prune after 10 s.
- `test_card_heartbeat`: in a temp dir, `update` writes `cdj.rgba`; set the mtime 10 s in the past; `heartbeat` with a fake `now` touches it; assert mtime is recent.
- `test_card_removed`: `remove()` unlinks it; a second `remove()` is harmless.
- `test_card_uses_selected_art`: the publisher receives the selected deck's art, not the other deck's.

- [ ] **Step 2: Run and verify failure**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_nexxbeatd`
Expected: new tests fail (missing `ArtCache`/`CardPublisher`).

- [ ] **Step 3: Implement**

- `ArtCache`: `dict[(deck, track_id)] -> dict[int, bytes]` plus `count`; `add` stores `payload` at `index`; when all `0..count-1` present, store the joined JPEG in a completed dict; cap at four completed entries; `prune(t)` drops buffers older than 10 s.
- On a status `track_id` change for a deck, drop that deck's incomplete buffers.
- `CardPublisher`: on `update`, render only if `(deck, bpm rounded to 0.1, master, art bytes)` changed; write atomically. `heartbeat(t)` touches the mtime every 2 s while the selected deck is playing or held. `remove()` after 5 s idle.
- The daemon calls `CardPublisher` only when a deck is selected; it passes the selected deck's cached art; no card while idle.

- [ ] **Step 4: Run and verify pass**

`cd ~/src/nexxhub/hub && python3 -m unittest -v test_nexxbeatd`
Expected: pass.

- [ ] **Step 5: Snapshot**

`~/src/nexxhub/snap.sh hub/nexxbeatd.py hub/test_nexxbeatd.py`

---

### Task 7: `djl_sim.py` and the end-to-end daemon integration test

**Files:**
- Create: `~/src/nexxhub/hub/djl_sim.py`
- Create: `~/src/nexxhub/hub/test_integration.py` (or a documented shell test)

**Interfaces:**
- Consumes: `djl_protocol.keepalive/send_cdj/parse_status`, the daemon env ports.
- Produces: a simulator that binds the announce/status ports, replies to the daemon's keep-alive with `0x10`, waits for `0x11`, then sends `0x0a` at ~5.86 Hz with a synthetic counter; CLI `--announce-port --status-port --bpm --pitch --deck --duration --pause-after --bpm-change-after --track-change-after --art`.

- [ ] **Step 1: Run the simulator against the daemon**

Copy the simulator to the Mac (`scp -o BatchMode=yes -o UserKnownHostsFile=/Users/cxfxcxb/nexxxen/dsp-tools/known_hosts_nexxxen nexxxen:~/src/nexxhub/hub/djl_sim.py /tmp/djl_sim.py`), then run `python3 /tmp/djl_sim.py --announce-port 60000 --status-port 60002 --bpm 176 --pitch 1.2 --deck 9 --duration 20 &` (allow Python through the macOS firewall if prompted).
On the Pi: `NB_RUN_DIR=/tmp/nb-sim NB_ANNOUNCE_PORT=60000 NB_STATUS_PORT=60002 NB_BROADCAST_ADDR=255.255.255.255 python3 ~/src/nexxhub/hub/nexxbeatd.py`.
Expected: within 2 s `/tmp/nb-sim/beat` shows `2 1 176.0 ... 1 ...`; the deck is 1, confidence > 0.3 after ~5 s.

- [ ] **Step 2: Write the failing integration test**

Create `test_integration.py` (run on the Pi with the simulator on the Mac; skip if the simulator is unreachable):
- Start the daemon in a subprocess with a temp run dir and ports 60100/60102; start the simulator on the Mac (the test can be split into two shells; if automated, use `NB_SIM_HOST`).
- Wait ≤ 5 s for the state line `source=2`, `playing=1`, `bpm≈176`.
- Send a pause status (the simulator CLI `--pause-after 5`), assert the state line has `playing=0` and that no pulse is produced (the daemon writes source 2 but playing 0; the visualizer decides).
- Change BPM to 180 (simulator `--bpm-change-after 8`), assert re-lock within 2 s.
- Send a track change (simulator `--track-change-after 12`, new track ID and a jumped counter), assert the clock re-anchors and the state does not emit a burst of beats.
- Kill the simulator; assert the daemon keeps running and falls back to the idle state after the timeout.
The test may be a shell script `test_integration.sh` with `grep`/`awk` assertions; keep it outside the unit-test discovery.

- [ ] **Step 3: Run and verify failure**

Run the test without the simulator.
Expected: fails to see `source=2` (timeout).

- [ ] **Step 4: Implement the simulator**

- Bind the announce port; on the daemon's keep-alive, record the source IP and reply with the 36-byte `0x10` packet (`HEADER + 0x10 + "OPUS-QUAD"` padded to 20 bytes + `01 00 09 00 00`).
- Bind the status port; wait for `0x11`; then send `0x0a` status packets at 5.86 Hz. Build a 293-byte status: header + `0x0a` + `"OPUS-QUAD"` padded 20; set `0x21=deck`, `0x22=257` (u16), `0x28=deck`, `0x2c=track_id` (u32 BE), `0x7c="1.30"`, `0x89=0xec` (playing/master/on-air), `0x8d=pitch_raw` (3 BE), `0x92=bpm_raw` (u16), `0xa2=counter` (u16); the counter increments at `bpm_eff/60`.
- Options: `--pause-after`, `--bpm-change-after`, `--track-change-after`, `--art FILE` (optional; split into 512-byte `0x56` subtype 2 packets with index/count).

- [ ] **Step 5: Run and verify pass**

Start the simulator and daemon again; the integration test passes; the state line changes on pause/tempo change; killing the simulator leads to idle after the timeout.

- [ ] **Step 6: Snapshot**

`~/src/nexxhub/snap.sh hub/djl_sim.py hub/test_integration.py`

---

### Task 8: C beat-state parser and `iBeat` uniforms in `nexxvis`

**Files:**
- Create: `~/src/nexxhub/vis/beatstate.h`
- Create: `~/src/nexxhub/vis/beatstate.c`
- Create: `~/src/nexxhub/vis/test_beatstate.c`
- Modify: `~/src/nexxhub/vis/nexxvis.c`
- Modify: `~/src/nexxhub/vis/build.sh` (add `beatstate.c`, build the test)

**Interfaces:**
- Produces:
  `typedef struct { int source, deck, playing, track_id; double bpm, phase, confidence, write_mono; } BeatState;`
  `int beatstate_parse(const char *line, BeatState *out);` (1 ok, 0 bad)
  `int beatstate_live(const BeatState *s, double now, double max_age);`
  `double beatstate_phase(const BeatState *s, double now);`
  `double beatstate_next_beat(const BeatState *s, double now, double offset_s);`

- [ ] **Step 1: Write the failing C test**

`test_beatstate.c`: parse `"2 1 176.07 0.4312 0.94 1 123456.789 1217\n"` → source 2, deck 1, bpm 176.07, phase 0.4312, confidence 0.94, playing 1, write_mono 123456.789, track 1217; `beatstate_live(s, 123457.0, 1.0) == 1`, `... 123458.0 ... == 0`; `beatstate_phase(s, 123456.789 + 0.1)` ≈ 0.4312 + 0.1*176.07/60 (mod 1) within 1e-3; reject `"0 0"` and garbage.

- [ ] **Step 2: Run and verify failure**

`cd ~/src/nexxhub/vis && gcc -O2 -Wall -o test_beatstate test_beatstate.c beatstate.c -lm`
Expected: link/compile error (no `beatstate.c` yet).

- [ ] **Step 3: Implement `beatstate.[ch]`**

`beatstate_parse` uses `sscanf(line, "%d %d %lf %lf %lf %d %lf %d", ...)` and requires exactly 8 fields; clamp phase to 0..1. `beatstate_phase` = `fmod(phase + (now-write_mono)*bpm/60, 1.0)` with negative guard; `0.0` if `bpm <= 0`. `beatstate_next_beat` = `now + (1 - phase(now))*60/bpm + offset_s`; `INFINITY` if `bpm <= 0`. `beatstate_live` = `fabs(now - write_mono) <= max_age`.

- [ ] **Step 4: Run and verify pass**

`cd ~/src/nexxhub/vis && gcc -O2 -Wall -o test_beatstate test_beatstate.c beatstate.c -lm && ./test_beatstate`
Expected: `ok`.

- [ ] **Step 5: Wire the parser into `nexxvis.c` and add the uniforms**

- Add `#include "beatstate.h"`; env `NV_BEAT_FILE` (default `/run/nexxbeat/beat`), `NV_BEAT_OFFSET_MS` (0), `NV_BEAT_LOG` (0).
- In the render loop, read the file (`fopen`/`fgets`, no lock needed due to atomic replace). If `beatstate_live(&bs, now, 1.0)` and `bs.source == 2` and `bs.playing`, use the DJ clock: `pulse` is 1.0 when `now` crosses `beatstate_next_beat` (track the last pulse time and the period), decaying `exp(-dt/0.12)`; `phase = beatstate_phase(&bs, now)`; `bpm = bs.bpm`; `conf = bs.confidence`; source 2.
- Extend `FS_HEAD` and `Viz` with `uniform vec4 iBeat; uniform float iBPM;` and `uBeat`, `uBPM`; set `glUniform4f(uBeat, pulse, phase, source, conf)` and `glUniform1f(uBPM, bpm)` per frame. (An unused uniform has location -1; setting it is a no-op.)
- Leave the audio fallback for Task 9 (for now, source 0 when no DJ state).

- [ ] **Step 6: Verify with the simulator**

Run the simulator from Task 7 and the daemon. Add a temporary drop-in `/etc/systemd/system/nexx-visualizer.service.d/20-debug.conf` containing `[Service]` and `Environment=NV_BEAT_LOG=1`; `daemon-reload`, restart the visualizer. Read the journal for `beat: dj 1 176.0 conf=...` lines and the shader load lines; remove the drop-in afterwards.
Expected: the log shows source 2 and bpm 176.0; no GL errors.

- [ ] **Step 7: Snapshot**

`~/src/nexxhub/snap.sh vis/beatstate.h vis/beatstate.c vis/test_beatstate.c vis/nexxvis.c vis/build.sh`

---

### Task 9: C PipeWire onset/BPM detector

**Files:**
- Create: `~/src/nexxhub/vis/beatdetect.h`
- Create: `~/src/nexxhub/vis/beatdetect.c`
- Create: `~/src/nexxhub/vis/test_beatdetect.c`
- Modify: `~/src/nexxhub/vis/nexxvis.c` (feed the detector from the existing FFT; use it when no fresh DJ state)
- Modify: `~/src/nexxhub/vis/build.sh`

**Interfaces:**
- Produces:
  `typedef struct BeatDetector BeatDetector;`
  `void bd_init(BeatDetector *d, double t);`
  `void bd_update(BeatDetector *d, const float *mag, int bins, double t);` (`mag[k] = sqrt(re^2+im^2)` for low bins, 48 kHz / 2048 FFT)
  `double bd_pulse(const BeatDetector *d, double t);`
  `double bd_phase(const BeatDetector *d, double t);`
  `double bd_bpm(const BeatDetector *d);`
  `double bd_confidence(const BeatDetector *d);`

- [ ] **Step 1: Write the failing test**

`test_beatdetect.c`: synthesize 10 s at 60 updates/s; bins 0..40; every 0.5 s (120 BPM) add a 3-frame pulse to bins 0..8 and a smaller pulse to bins 9..20; feed `bd_update`; assert `bd_bpm` ≈ 120 ± 3 and `bd_confidence > 0.5`; predict beats and assert the predicted time is within 20 ms of a true beat. Feed silence for 2 s → `bd_confidence == 0` and `bd_pulse` decays. Feed random noise → confidence < 0.3.

- [ ] **Step 2: Run and verify failure**

`cd ~/src/nexxhub/vis && gcc -O2 -Wall -o test_beatdetect test_beatdetect.c beatdetect.c -lm`
Expected: compile/link error.

- [ ] **Step 3: Implement `beatdetect.[ch]`**

- Keep the last ~100 frames of `log1p(mag)` sums over bins 1..40; per frame `flux = Σ max(0, logmag - prev_logmag)`.
- Rolling median of flux (100 frames) + `delta = 0.35 * MAD`; onset when `flux > median + delta` and `t - last_onset > 0.12`.
- Store onset times/strengths for 8 s. Build an inter-onset interval histogram (0.30–1.00 s, 4 ms bins, Gaussian ±1 bin); pick the strongest period; smooth over 4 s; reject if fewer than 3 onsets.
- Phase anchor = the min-residual estimate over the last 16 onsets (same idea as `BeatClock`); `pulse` = 1 at each predicted beat, decay `exp(-dt/0.12)`; `phase = fmod(t-anchor, period)/period`; confidence from the histogram peak and onset count; 0 when the input is silent or stale (>0.5 s since the last frame).
- Keep the detector CPU O(bins+100); no allocations per frame.

- [ ] **Step 4: Run and verify pass**

`cd ~/src/nexxhub/vis && gcc -O2 -Wall -o test_beatdetect test_beatdetect.c beatdetect.c -lm && ./test_beatdetect`
Expected: `ok` (bpm 117–123, phase < 20 ms, silence 0, noise < 0.3).

- [ ] **Step 5: Wire the detector into `nexxvis.c`**

- After the existing FFT, compute `mag[k] = sqrt(re[k]^2+im[k]^2)` for `k=1..40`; call `bd_update(&bd, mag, 40, t)`.
- Source arbitration: if the DJ state is live and `playing`, use it; else use the detector. `iBeat = (pulse, phase, source, conf)`; `iBPM` = DJ bpm or `bd_bpm`.
- `NV_BEAT_LOG=1`: once per second log `beat: source=%d bpm=%.1f conf=%.2f` to stderr.
- Keep the existing spectrum/waveform/`iLevel` path unchanged.

- [ ] **Step 6: Verify with a click track**

Generate `click120.wav` (10 s of 1 kHz 20 ms clicks at 120 BPM) on the Pi with Python/numpy; `pw-play --target speakereq2x2 click120.wav &`; add the same temporary debug drop-in (Task 8), restart, read the journal.
Expected: `bpm≈120`, `source=1`, confidence > 0.5, steady pulses.

- [ ] **Step 7: Snapshot**

`~/src/nexxhub/snap.sh vis/beatdetect.h vis/beatdetect.c vis/test_beatdetect.c vis/nexxvis.c vis/build.sh`

---

### Task 10: Shader beat accents and `40-beat.frag`

**Files:**
- Modify: `~/src/nexxhub/vis/shaders/10-aurora.frag`
- Modify: `~/src/nexxhub/vis/shaders/20-spectral-ring.frag`
- Modify: `~/src/nexxhub/vis/shaders/30-spectrum-tunnel.frag`
- Create: `~/src/nexxhub/vis/shaders/40-beat.frag`
- Modify: `~/src/nexxhub/vis/nexxvis.c` only if the shader compile check reveals a header issue.

**Interfaces:**
- Consumes: `iBeat` (`x` pulse 0..1, `y` phase 0..1, `z` source 0/1/2, `w` confidence) and `iBPM` from Task 8/9.

- [ ] **Step 1: Add the subtle accents**

In each existing shader, add `float beat = iBeat.x * iBeat.w;` and one line:
- `10-aurora`: `col *= 1.0 + 0.10 * beat;` and lift the curtain base by `0.02*beat`.
- `20-spectral-ring`: `R += 0.05 * beat;` and add `col += hue * 0.15 * beat * exp(-abs(r-R)*20.0);`.
- `30-spectrum-tunnel`: `float speed = 0.6 + 2.2 * energy + 0.8 * beat;`.
Keep all changes confidence-weighted; in silence `beat=0` and the look is unchanged.

- [ ] **Step 2: Add `40-beat.frag`**

Create a cheap club-style shader (0.33 scale):
```glsl
// Beat bloom: expanding rings on each beat; spectrum shapes the ring; bass glows the core.
// nv:scale=0.33
float spec(float x){ return texture(iChannel0, vec2(clamp(x,0.0,1.0),0.25)).r; }
void mainImage(out vec4 c, in vec2 p){
  vec2 q = (p - 0.5*iResolution.xy) / iResolution.y;
  float r = length(q), a = atan(q.y,q.x);
  float beat = iBeat.x * iBeat.w, ph = iBeat.y, bass = iLevel.x, treb = iLevel.z;
  vec3 col = vec3(0.008,0.010,0.025);
  col += vec3(0.05,0.03,0.10) * (1.0 - r*0.8);
  for (int k=0;k<3;k++){
    float fk=float(k);
    float ring = fract(ph + fk*0.333);
    float rad = 0.10 + 0.55*ring;
    float band = spec(fract(fk*0.21 + 0.05));
    float w = 0.006 + 0.02*band + 0.01*beat;
    float glow = exp(-abs(r-rad)/w) * (0.35 + 0.8*beat) * (1.0 - ring*0.6);
    vec3 hue = 0.5 + 0.5*cos(6.2831*(fk*0.18 + iTime*0.04 + vec3(0.0,0.33,0.67)));
    col += hue * glow * (0.6 + 0.9*band);
  }
  col += vec3(1.0,0.55,0.25) * exp(-r*(12.0 - 5.0*bass)) * (0.15 + 1.2*beat);
  col += vec3(0.4,0.7,1.0) * exp(-r*5.0) * bass * 0.25;
  float sp = fract(sin(dot(floor(p/2.0), vec2(12.9898,78.233)) + floor(iTime*10.0))*43758.5);
  col += step(0.998 - 0.0015*treb, sp) * smoothstep(0.7,0.2,r) * treb * 0.6;
  col *= 1.0 + 0.10*beat*beat;
  c = vec4(1.0-exp(-col*1.6), 1.0);
}
```

- [ ] **Step 3: Compile-check the shaders**

Restart the visualizer (or run with the new shaders) and read the journal for `nexxvis: loaded ...` and `compile error`. Run `NV_FPS_LOG=1` and check ≥ 50 fps at `0.375` with the new shader active (wait for the 300 s cycle or temporarily set `NV_CYCLE=5` in a test service override).
Expected: four shaders load; `40-beat.frag` compiles; fps ≥ 50.

- [ ] **Step 4: Visual check**

With the simulator or a click track running, confirm on the TV: the ring expands on each beat, the flash is comfortable, the existing shaders get a subtle pulse, and silence looks unchanged. Tune `0.10`/`0.15` if it is too strong.

- [ ] **Step 5: Snapshot**

`~/src/nexxhub/snap.sh vis/shaders vis/nexxvis.c`

---

### Task 11: CDJ card drawing in `nexxvis`

**Files:**
- Modify: `~/src/nexxhub/vis/nexxvis.c`
- Test: `~/src/nexxhub/vis/test_beatstate.c` only if a pure helper is added

**Interfaces:**
- Consumes: `NV_CDJ_CARD` (default `/run/nexxbeat/cdj.rgba`), the existing `load_rgba`/`poll_nowplaying` pattern.

- [ ] **Step 1: Add the card polling and priority**

- Add `NV_CDJ_CARD`; poll it at 0.5 s like `nowplaying.rgba`; keep a second `Img` and its mtime.
- Freshness: `now - mtime < 5 s`. If fresh, draw the CDJ card at the now-playing position (`W*0.035`, `H - nh - H*0.06`, scaled by `W/2560`) and skip the now-playing card. If the menu is visible, hide both. If stale/absent, draw the now-playing card as today.
- Fade the CDJ card in/out over ~0.6 s like the now-playing card.
- No title/artist is drawn by `nexxvis`; the daemon owns the card pixels.

- [ ] **Step 2: Create a card fixture and verify**

Run the daemon + simulator with album art (Task 7), or copy a card produced by `card.py` to `/run/nexxbeat/cdj.rgba`. Restart the visualizer. Expected on the TV: the CDJ card appears bottom-left; after 5 s without a heartbeat it fades and the Spotify/now-playing card (if any) returns.
Use `sudo journalctl -u nexx-visualizer -n 50`. Confirm no `load_rgba` errors.

- [ ] **Step 3: Snapshot**

`~/src/nexxhub/snap.sh vis/nexxvis.c`

---

### Task 12: `nexxbeatd.service`, env, install/rollback

**Files:**
- Create: `~/src/nexxhub/units/nexxbeatd.service`
- Modify: `~/src/nexxhub/units/nexx-visualizer.service` (add `NV_BEAT_FILE`, `NV_CDJ_CARD`)
- Create: `~/src/nexxhub/install.sh`
- Test: shell checks (`bash -n`, `--dry-run`, `systemd-analyze verify`)

**Interfaces:**
- Produces: `install.sh` with `--dry-run` and `--rollback`; the unit files above.

- [ ] **Step 1: Write the daemon unit**

`units/nexxbeatd.service` exactly as in the spec §8.5 (`User=cxfxcxb`, `RuntimeDirectory=nexxbeat`, `RuntimeDirectoryMode=0755`, `ExecStart=/usr/bin/python3 /usr/local/lib/nexxhub/nexxbeatd.py`, `Restart=always`, `RestartSec=3`, `WantedBy=multi-user.target`). Add `Environment=NB_RUN_DIR=/run/nexxbeat` (the daemon writes both files there).

- [ ] **Step 2: Add the visualizer env**

In `units/nexx-visualizer.service`, add:
`Environment=NV_BEAT_FILE=/run/nexxbeat/beat`
`Environment=NV_CDJ_CARD=/run/nexxbeat/cdj.rgba`
Keep `NV_MODE=2560x1440@60`, `NV_SCALE=0.375`, `NV_CYCLE=300`, `NV_SINK=speakereq2x2` from Task 1.

- [ ] **Step 3: Write `install.sh`**

- `--dry-run`: print every command, touch nothing.
- Baseline sync: ensure the source unit has the live env values and the aurora scale is `0.25`; abort with a clear message if the source differs in an unexpected way.
- Back up `/usr/local/bin/nexxvis` to `nexxvis.bak-YYYYMMDD-HHMM`, the installed unit files, and the whole `/usr/local/share/nexxvis/shaders/` directory to `/var/backups/nexxxen/nexxvis-YYYYMMDD-HHMM/`.
- Run `vis/build.sh` first. Install: `vis/nexxvis`, `vis/shaders/*.frag`, `hub/nexxbeatd.py`, `hub/djl_protocol.py`, `hub/beatclock.py`, `hub/card.py`, `units/nexxbeatd.service`, `units/nexx-visualizer.service`; `systemctl daemon-reload`.
- `systemctl enable --now nexxbeatd`.
- Restart the visualizer only if active: `systemctl is-active --quiet nexx-visualizer && systemctl restart nexx-visualizer`.
- `--rollback`: restore the binary, the shader dir (delete `40-beat.frag` if it was not in the backup), and the service files; `systemctl disable --now nexxbeatd`; `daemon-reload`; restart the visualizer only if active.
- `set -eu`, quote paths, no `rm -rf` outside `/var/backups` and the shader dir.

- [ ] **Step 4: Verify the script**

`bash -n ~/src/nexxhub/install.sh`; `~/src/nexxhub/install.sh --dry-run` (no changes); `systemd-analyze verify ~/src/nexxhub/units/nexxbeatd.service`.
Expected: no syntax errors; dry-run prints the actions; unit verifies.

- [ ] **Step 5: Install and verify the units**

Run `sudo ~/src/nexxhub/install.sh`. `systemctl status nexxbeatd` (active); `systemctl cat nexx-visualizer | grep NV_` (new env); `sudo journalctl -u nexxbeatd -n 20` (no traceback); `/run/nexxbeat` exists and is owned by `cxfxcxb`.
Expected: daemon active, visualizer restarted only if it was active; no other screen mode stopped.

- [ ] **Step 6: Test rollback and reinstall**

`sudo ~/src/nexxhub/install.sh --rollback`; check the old binary/shaders are back, `nexxbeatd` inactive, the visualizer still active if it was; then `sudo ~/src/nexxhub/install.sh` again.
Expected: clean restore and reinstall.

- [ ] **Step 7: Snapshot**

`~/src/nexxhub/snap.sh units/nexxbeatd.service units/nexx-visualizer.service install.sh`

---

### Task 13: On-device acceptance, 5-minute validation, docs, local mirror

**Files:**
- Modify: `/Users/cxfxcxb/nexxxen/docs/superpowers/specs/2026-11-22-nexxvis-beat-reactive-design.md` (record verified results, if needed)
- Create: `/Users/cxfxcxb/nexxxen/nexxbeat-recon/README.md` (how to run the simulator, where the capture is)
- Copy: the changed source to `/Users/cxfxcxb/nexxxen/nexxhub/`

- [ ] **Step 1: Simulator acceptance**

Run the simulator on the Mac and the installed daemon on the Pi (with the real ports if no OPUS is active? Use a temporary `systemctl stop`? Prefer test ports in a manual run). Confirm: card appears, pulse, pause → no pulse, tempo change → re-lock, simulator killed → idle. Record the state lines and journal excerpts.

- [ ] **Step 2: Real OPUS-QUAD acceptance**

Ask the user to load and play a track on the OPUS-QUAD (deck 1). Confirm: the card shows `PRO DJ LINK · DECK 1`, BPM, art; the visuals pulse; the pulse is within 50 ms after 10 s (ask the user; optionally tune `NV_BEAT_OFFSET_MS`). Pause → no pulse; deck switch → follows within 1 s; tempo change → re-lock within 2 s; stop → card fades and disappears.

- [ ] **Step 3: PipeWire acceptance**

Play Spotify/AirPlay (the user's normal path). Confirm the visuals pulse from audio; `NV_BEAT_LOG=1` shows `source=1 bpm≈...`; the now-playing card still works when no DJ card is present. Silence → no pulses.

- [ ] **Step 4: Regression and reboot**

Check the launcher menu (gamepad/TV remote), `nexxhub-ctl kodi` / back to `vis`, `source-switch` behavior, and a reboot: `nexxbeatd` active, `nexx-visualizer` active, the OPUS is re-discovered when playing. Compare journal errors before/after; check CPU (`top`) and temperature (`vcgencmd measure_temp`) with `cec_remote.py` as-is.

- [ ] **Step 5: 5-minute mix capture**

Capture the status stream for 5 minutes while the user mixes (track changes, tempo changes, deck switches). Store the log under `/Users/cxfxcxb/nexxxen/nexxbeat-recon/`. Analyze the counter increments and phase error; record the result in the design doc's Appendix A or a new `nexxbeat-recon/README.md`.

- [ ] **Step 6: Sync the local mirror and update docs**

`mkdir -p /Users/cxfxcxb/nexxxen/nexxhub && scp -r nexxxen:~/src/nexxhub/hub nexxxen:~/src/nexxhub/vis nexxxen:~/src/nexxhub/units nexxxen:~/src/nexxhub/install.sh /Users/cxfxcxb/nexxxen/nexxhub/` (or a targeted copy). Add a short README in `nexxbeat-recon/` with the simulator command, the capture path, and the acceptance results. Update the design doc only where a measured value differs from the plan.
Expected: the local mirror matches the Pi; the docs record the verified behavior.

- [ ] **Step 7: Final snapshot**

`~/src/nexxhub/snap.sh hub vis units install.sh`

---

## Self-Review Notes

- Spec coverage: §8.1–8.8 mapped to Tasks 2–12; §10 tests in Tasks 2–9 and 13; §11 acceptance in Task 13; §13 v1.1 explicitly out of scope; §15 calls implemented by the file/heartbeat/selection/install rules.
- Types: `Status`/`Metadata` fields are defined once in Task 2 and consumed by Tasks 5–7; `BeatState` is defined in Task 8 and written by Task 5's `format_state`; the state line has exactly 8 fields in both.
- The C build links `beatstate.c`/`beatdetect.c` and their tests; the Python tests use `python3 -m unittest` from `hub/`.
- Not a git repo: snapshot steps replace commits, per the approved design.
