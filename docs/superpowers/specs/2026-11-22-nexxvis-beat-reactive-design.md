# nexxvis beat-reactive screensaver — design

Date: 2026-11-22
Device: `nexxxen` — Raspberry Pi 4 (4 GB), HiFiBerryOS NG, HDMI TV on tty1
Status: design for approval (v1); v1.1 metadata follow-up sketched at the end

---

## 1. Intent and why

The TV currently shows `nexxvis`, a GLSL visualizer that is the hub's idle
("screensaver") screen. It reacts to the PipeWire sink's spectrum but has no
sense of rhythm: it cannot pulse on a beat, and when the DJ plays the
OPUS-QUAD through the DSP's optical input the Pi hears nothing at all.

The goal is to make the existing screensaver **beat-locked**:

- When the OPUS-QUAD is playing (over Wi-Fi), follow its beat clock and show
  a small now-playing card with the deck, BPM and album art.
- When the Pi itself plays something (Spotify Soloist, AirPlay, Moonlight),
  detect beats from the PipeWire stream instead.
- Never invent beats in silence; keep the existing visual style, screen-mode
  switching, launcher overlay and now-playing card working unchanged.

This is for listening/DJ sessions on the rooftop system: the TV should feel
connected to the music whether the source is the Pi or the DJ deck.

## 2. Goals

1. Pulse/breathe on the actual beat for OPUS-QUAD playback, from Wi-Fi only
   (no optical/DSP/DSP-program changes, no extra hardware).
2. Pulse on beats for PipeWire playback (Spotify/AirPlay/Moonlight).
3. Show a small `PRO DJ LINK` card: deck, effective BPM, pitch, album art.
4. Survive restarts, Wi-Fi reconnects, deck switches, tempo changes and the
   deck's undocumented protocol behaviour.
5. Stay within the Pi 4's CPU/thermal budget and leave the existing
   `nexxhub` screen modes untouched.

## 3. Non-goals (v1)

- Track title/artist. The OPUS-QUAD does not serve them over the network.
  (v1.1: match against the USB library; see §13.)
- Capturing the optical input into PipeWire. (Deferred; see §13.)
- DSP program changes, driver/kernel changes, audio routing changes.
- A new screen mode or changes to `nexxhub`'s menu/timeouts.
- Cloud services, Shazam/fingerprinting, or any network egress.
- A mobile app or web UI.

## 4. Anti-goals (what would make this a failure)

- Visuals that claim a beat when nothing is playing (fake pulses in silence).
- A beat pulse that visibly lags the music by a large fraction of a beat.
- The launcher menu, Kodi/Artemis/RetroArch switching, the now-playing card
  or `source-switch` regressing.
- A fragile daemon that needs manual restarting after Wi-Fi drops or after
  the OPUS-QUAD changes IP.
- Burning a CPU core or triggering thermal throttling.

## 5. Current state (verified 2026-11-22)

- `nexxhub` (system service, `/usr/local/lib/nexxhub/nexxhub.py`) chooses the
  tty1 mode. `vis` is the default and also the idle screen:
  `nexx-visualizer.service` runs `/usr/local/bin/nexxvis`, a C program
  (`~/src/nexxhub/vis/nexxvis.c`) that renders GLSL shaders through
  DRM/GBM/EGL, 2560x1440@60, with `NV_SCALE=0.375`.
- `nexxvis` captures the `speakereq2x2` sink monitor with
  `pw-record --raw` (48 kHz stereo f32), keeps a 2048-sample ring, computes a
  2048-point FFT and publishes a 512-bin log spectrum + 512 waveform samples
  as `iChannel0`; it derives `iLevel` (bass/mid/treble/overall) with a slow AGC.
- Shaders are files in `/usr/local/share/nexxvis/shaders/*.frag`:
  `10-aurora.frag`, `20-spectral-ring.frag`, `30-spectrum-tunnel.frag`.
  They cycle every `NV_CYCLE=300` s with a fade through black.
- `nexxvis` already polls `/run/nexxhub/menu` (launcher overlay state) and
  `/run/nexxhub/nowplaying.rgba` (a Pillow-rendered card from
  `nowplaying.py`). It hides the card while the menu is visible and fades it
  based on file presence.
- The Pi's `wlan0` is <pi-ip>/24; the OPUS-QUAD is on the same Wi-Fi
  (seen at <deck-ip>, device name `OPUS-QUAD`). The Pi has no ALSA
  capture device; the DSP's optical input is not visible to ALSA/PipeWire.
- The Pi has no Java, pip, `pyrekordbox` or SQLCipher. System Python has
  Pillow and numpy; gcc, EGL/GLES/GBM/DRM dev libs are installed.
- A pre-existing `cec_remote.py` process is pinning one CPU core at ~100 %
  (separate bug; see §12).
- **Source-tree drift (2026-11-22):** the installed production files differ
  from `~/src/nexxhub`: the live unit has `NV_MODE=2560x1440@60`,
  `NV_SCALE=0.375` and the live `10-aurora.frag` has `nv:scale=0.25`, while
  the source copies have `1920x1080@60`, `0.5` and `0.34`. The binaries are
  identical. The live values are the baseline; install must sync the source
  tree to the live files first (then add the new env vars), never install the
  stale source as-is.

## 6. Constraints

- OPUS-QUAD is **not** a full Pro DJ Link player: no `0x28` beat packets and
  no title/artist over the network. In the rekordbox handshake mode used here
  there is no high-precision playhead either. (A CDJ-style keep-alive
  reportedly enables absolute-position packets but disables the song-load
  metadata/PSSI that the album art depends on; see §14 — the counter+PLL keeps
  the art and is sufficient.) It broadcasts `0x06` keep-alives and only sends
  status after a rekordbox-style handshake.
- Status packets are **unicast** to the client after the handshake, ~5.86 Hz
  per deck, 293 bytes, with the standard CDJ layout plus 81 extra bytes.
- Deck numbers are 9–12 (display 1–4).
- The undocumented 16-bit beat counter at `0xa2–0xa3` increments by 1 per beat
  and matches `BPM × pitch`. This is the beat clock. It is undocumented and
  may change with firmware; a BPM-only fallback is required.
- The Pi is the I2S clock master for the DSP; no audio capture will be added
  in v1.
- The daemon must run unprivileged and must not require network egress.

## 7. Approaches considered

### 7.1 Where the beat logic lives

**A. Split by job — chosen.** Python daemon (`nexxbeatd`) for the network
protocol, beat counter/phase state and the Pillow card; `nexxvis` (C) keeps
the real-time audio capture and adds the PipeWire onset/BPM detector.
- Pros: the pulse stays in the renderer's 60 fps loop; Python is the right
  place for UDP parsing and text/art rendering; it matches the existing
  `/run/nexxhub` file contract; the daemon can be restarted/simulated without
  touching the display.
- Cons: one more process/unit; a small polling IPC.

**B. All inside `nexxvis` (C).** One process, lowest latency, but ~300 lines
of UDP parsing plus a text/card renderer in C (the current overlay is
pre-rendered RGBA). Riskier to the renderer; harder to test. Rejected.

**C. All in Python.** A single daemon captures PipeWire audio too (numpy),
computes beats and renders the card; `nexxvis` only exposes uniforms.
Minimal renderer changes, but it captures the same audio twice, adds Python
timing jitter to the pulse, costs CPU, and still needs the C uniform plumbing.
Rejected.

### 7.2 Audio path for the DJ source

- **Beats only over Wi-Fi — chosen for v1.** No hardware, no DSP work. The
  status beat counter gives the beat clock; the spectrum is unavailable for
  the DJ source (the shaders still animate on the beat and on `iLevel` from
  whatever else is in PipeWire).
- **DSP breakout to the Pi's I2S input.** Feasible in principle (route
  ASRC7/SPDIF RX to `SDATA_OUT1/2`, jumper to header pin 38, add a capture
  overlay), but needs board-level clock verification + a custom ASoC
  capture driver + a keep-alive stream. Deferred.
- **USB S/PDIF receiver on a splitter.** Reliable, zero DSP work, extra
  hardware. Deferred; the fallback if audio-reactive spectrum from the DJ
  source becomes a requirement.

### 7.3 Overlay metadata

- **Album art + deck + BPM — chosen for v1.** All confirmed live.
- **Title/artist via the USB library (`OpusProvider`-style PSSI matching)** —
  v1.1; needs the USB data and a pure-Python port (§13).
- **Shazam/fingerprinting** — rejected: needs the deferred audio path, 5–10 s
  latency, poor hit rate on DJ edits/white labels, and a commercial/cloud API
  (privacy, cost). It identifies a recording, not the performance.

## 8. Design

### 8.1 Data flow

```
OPUS-QUAD (Wi-Fi)
   │  UDP 50000 keep-alive (client) / 0x06 (unit)
   │  UDP 50002: 0x10 reply, 0x0a status, 0x56 metadata
   ▼
nexxbeatd (Python, user cxfxcxb)
   │  status parse → beat counter → phase-locked clock
   │  deck selection, album art reassembly
   ├─ /run/nexxbeat/beat        (atomic text: source, deck, bpm, phase,
   │                             confidence, playing, write_mono, track_id)
   └─ /run/nexxbeat/cdj.rgba    (Pillow card; absent when idle)

nexxvis (C, tty1 renderer)
   ├─ reads beat file every frame; if fresh → DJ clock
   ├─ PipeWire capture → FFT → onset/BPM/phase detector (fallback)
   ├─ arbitrates source per frame → iBeat/iBeatPhase/iBPM/iBeatSource
   ├─ draws the CDJ card if fresh, else the now-playing card
   └─ shaders: existing 3 get a beat accent; new 40-beat.frag
```

### 8.2 `nexxbeatd` — Pro DJ Link daemon

**Sockets.** Bind UDP `0.0.0.0:50000` (keep-alive/receive) and
`0.0.0.0:50002` (status receive + handshake send). `SO_REUSEADDR` and
`SO_BROADCAST`; broadcast to `255.255.255.255:50000` (not the subnet-specific
address, so Wi-Fi reconnects are handled).

**Joining.** Every 2 s send the rekordbox keep-alive (54 bytes):

```
10-byte header: 51 73 70 74 31 57 6d 4a 4f 4c   ("Qspt1WmJOL")
06 00
"rekordbox" padded to 20 bytes with NULs
01 03 00 36 17 01
client MAC (6 bytes)
client IPv4 (4 bytes)
04 01 00 00 04 08
```

The OPUS-QUAD replies on `:50002` with a `0x10` packet (37+ bytes: header +
`10` + `"OPUS-QUAD"` padded 20 + 5 tail bytes). Record the source IP as the
unit IP. Send the `sendCdj` handshake (296 bytes):

```
header + 11 + "rekordbox" padded 20
+ 01 01 17 01 04 17 01 00 00 00
+ 255-byte "weird string": client name bytes at even offsets, zeros elsewhere
```

Resend `sendCdj` on start, whenever no status has been seen for > 3 s, and
every 30 s as a keep-alive. Re-detect the unit IP if status stops and the
`0x10`/`0x06` announcements move. Log handshake/reconnect events at 1 line
per state change, not per packet.

**Status parsing (`0x0a`, 293 bytes).**

| Field | Offset | Notes |
|---|---|---|
| header / type | 0x00 / 0x0a | 10-byte magic; type at 0x0a |
| device name | 0x0b | 20 bytes, NUL-padded (`OPUS-QUAD`) |
| payload length | 0x22 | u16 BE; packet size = value + 0x24 = 293 |
| deck number | 0x21 | 9–12; display 1–4 |
| track source | 0x28 | OPUS uses a player/source byte |
| rekordbox track ID | 0x2c | u32 BE; used as the art key |
| firmware | 0x7c | 4 ASCII (e.g. `1.30`) |
| pitch | 0x8d | 3 bytes BE, centre `0x100000`; percent = (raw−centre)/centre×100 |
| status flags | 0x89 | 0x40 playing, 0x20 master, 0x08 on-air, 0x10 synced, 0x02 BPM-sync |
| BPM | 0x92 | u16 BE, ×100 (track BPM) |
| beat counter | 0xa2 | u16 BE, undocumented; +1 per beat |
| beat in bar | 0xa6 | 0 on the OPUS-QUAD (do not rely on it) |

**Per-deck state.** Keep, per deck 9–12: `last_t`, `beat_counter` (unwrapped),
`bpm`, `pitch`, `flags`, `track_id`, `last_increment_t`, `playing`.

**Effective BPM.** `bpm_eff = bpm × (1 + pitch_pct/100)`. Validate against the
counter rate over a 10 s window; prefer the measured rate when it agrees
within 1 %, and use `bpm_eff` otherwise (it is stable when status is sparse).
Reject `bpm == 65535` (no track) and `bpm == 0`.

**Beat-counter handling.**
- Delta = new − old, with `+65536` if delta < −32768 (wrap).
- Delta 1 is the normal case; delta > 1 means missed status packets — treat
  as that many beats (the phase anchor still works).
- A jump > 16, a counter of 0/0xFFFF after a track change, or a track-ID
  change resets the phase estimator and re-anchors on the next increment.
- Stopped decks hold the counter; ignore increments while not playing.

**Phase estimator (min-residual PLL).**
- True beat period `T = 60 / bpm_eff`.
- Maintain an unbounded beat index `k` (unwrapped counter) and a ring of the
  last `N = 24` observations. For an increment observed at `t_recv`, the true
  beat time is in `(t_prev_status, t_recv]`; record
  `r = t_recv − k×T`.
- Estimate the phase anchor as a low percentile (e.g. the 10th percentile) of
  the ring `r` values: the earliest observed arrival is closest to the true
  beat, the rest are delayed by the status interval.
- Predicted next beat: `t_next = anchor + ceil((now − anchor)/T)×T`.
- Smooth `T` with a slow EMA toward `60/bpm_eff` (α ≈ 0.05) to avoid jitter
  from the 5.86 Hz status rate; re-seed on a track change.
- Apply a configurable `beat_offset_ms` (default 0; positive = pulse later)
  for the user to tune against what they hear.
- Confidence: `0..1` from the ring spread (p10 vs p50), the number of
  increments in the window, flag consistency, and the counter's agreement
  with BPM. When confidence < 0.2, the visualizer damps the beat accent.
- If no increments for > 2 s while playing, free-run from the last anchor
  with confidence ~0.3 and re-anchor on the next increment.

**Deck selection (every status tick).**
1. A deck with master + playing.
2. Else a deck with playing + on-air.
3. Else the deck that was playing most recently, for 5 s (pause/transition).
   The hold keeps that deck selected and its card visible, but the beat clock
   is inactive while the deck is not playing (`playing=0`), so a pause never
   produces invented pulses.
4. Else idle (`source=0`).
On a switch, publish the new deck's anchor immediately; the visualizer fades
the beat accent over ~0.3 s to soften the phase jump.

**State file.** `/run/nexxbeat/beat`, atomic write (`tmp` + `os.replace`),
0644, ~30 Hz:
```
<source> <deck> <bpm> <phase> <confidence> <playing> <write_mono> <track_id>
2 1 176.07 0.4312 0.94 1 123456.789 1217
```
`source`: 2 = Pro DJ Link (this daemon); 0 = idle. `phase` is the fraction of
the beat elapsed at `write_mono`. `write_mono` is `time.monotonic()` seconds.
`nexxvis` computes the current phase from the age. `playing` is the selected
deck's own status flag (`0x40`), not the daemon's selection state: the 5 s
post-stop hold does not set it, and the visualizer uses the DJ clock only when
`playing=1`. When idle, write `0 0 0 0 0 0 <mono> 0`.

**Card.** `/run/nexxbeat/cdj.rgba` (Pillow), 1180×300 at 2560-px reference
width, transparent background, same visual language as `nowplaying.py`:
album art (from `0x56` subtype 2), a `PRO DJ LINK · DECK n` tag, `MASTER` when
set, large BPM, pitch (`+1.2 %`), and a beat dot. No title/artist in v1.
Render on track/art/BPM/deck change (~2 Hz max), and **touch/rewrite the file
on a 2 s heartbeat while the selected deck is playing** so the visualizer's
mtime freshness rule does not hide a steady track's card. Remove the file
after 5 s idle. If the art is incomplete, use a music-glyph placeholder.

**Metadata packets (`0x56`).** Deck at 0x21, subtype at 0x25, u32 BE track ID
at 0x28, packet index at 0x31, count at 0x33, payload at 0x34. Subtype 2 is
JPEG album art (reassemble index/count, decode with Pillow; tolerate gaps).
Subtype `0x0a` is PSSI (reserved for v1.1). Ignore other subtypes in v1.
Keep a **per-deck art cache keyed by (deck, track ID)**: a track load on a
non-selected deck must not overwrite the selected deck's art. Drop incomplete
buffers after ~10 s; cap the cache at four entries.

**Failure handling.** No status > 3 s → re-handshake; > 10 s → idle state and
remove the card. Wi-Fi down → keep retrying every 2 s; no crash. A malformed
packet (< 0x24 bytes, wrong length) is logged once and skipped. The daemon
never writes outside `/run/nexxbeat` and its log.

### 8.3 `nexxvis` — rendering changes

**Beat state reader.** Read `NV_BEAT_FILE` (`/run/nexxbeat/beat`) every frame
with `sscanf`; use `clock_gettime(CLOCK_MONOTONIC)` for age. Freshness: age
< 1.0 s. If fresh and `source=2` and `playing=1` → DJ clock; else the audio
detector.

**PipeWire beat detector (fallback).** Add to the existing analysis path:
- Keep the previous raw FFT magnitude bins; per display frame compute a
  low-band spectral flux over bins covering ~30–800 Hz:
  `flux = Σ max(0, log(1+|X_k|) − log(1+|X_prev,k|))`.
- Adaptive threshold: rolling median of the last ~1.5 s plus a delta
  (`~0.35 ×` the median absolute deviation, tunable); refractory 120 ms.
- Onsets: keep the last 8 s of onset times and strengths.
- Tempo: inter-onset-interval histogram over 0.30–1.00 s (>2 onsets
  required); pick the strongest consistent period in 60–200 BPM; prefer
  70–180; smooth over ~4 s.
- Phase: anchor from the last onset and the period, with the same
  min-residual/EMA approach; confidence from interval consistency and signal
  level.
- Silence/stale audio (>0.5 s): no onsets, confidence 0, pulse decays.
- Do not change the existing spectrum/waveform or `iLevel` calculations.

**Uniforms.** Add to `FS_HEAD`:
```glsl
uniform vec4 iBeat;   // x: pulse 0..1, y: phase 0..1, z: source (0/1/2), w: confidence
uniform float iBPM;
```
`iBeat.x` is set to 1 on each beat and decays as `exp(-dt/0.12)` per frame
(audio onset or predicted DJ beat clock). `iBeat.y` is the fractional phase
since the last beat. `iBeat.z` is 0 (none), 1 (audio), 2 (Pro DJ Link).
`iBeat.w` is confidence; shaders multiply their beat effect by it.
`iBPM` is the effective BPM (0 when unknown).

**Source arbitration.** DJ link wins when fresh and playing; otherwise the
audio detector. If DJ confidence < 0.2, still use the DJ clock (avoid
double-pulsing) but let the shader damp the effect via `iBeat.w`. If the DJ
state disappears, the audio detector takes over on the next frame.

**Existing shaders.** Add a small, confidence-weighted beat accent:
- `10-aurora`: lift brightness / curtain height by `0.10 × pulse`.
- `20-spectral-ring`: ring radius + glow by `0.06 × pulse`; core flash.
- `30-spectrum-tunnel`: speed + center light by `0.15 × pulse`.
Keep the changes subtle; the shaders must still look right in silence.

**New shader `40-beat.frag`.** Punchy club style, cheap for the Pi 4:
- Dark radial background, slow hue rotation.
- 3 expanding rings whose radius is derived from `iBeat.y` (current phase),
  one ring per beat; brightness `iBeat.x`; a screen flash `iBeat.x² × 0.12`.
- Spectrum (`iChannel0`) modulates ring thickness and sparkle; bass drives a
  central glow; treble sparkles. `// nv:scale=0.33` to keep the GPU cost low.
- No strobe above ~3 Hz; the effect must stay comfortable.

**Card drawing.** Poll `NV_CDJ_CARD` at 0.5 s like the now-playing card. If
the file exists and is fresh (<5 s), draw it bottom-left at the same
position/size scaling and hide the now-playing card. If both exist and the
CDJ card is stale, fall back to the now-playing card. The menu overlay still
hides both. Reuse the existing `load_rgba`/`poll_nowplaying` machinery with a
second `Img` and a freshness check (mtime + `stat`). The daemon's 2 s
heartbeat keeps the mtime fresh while playing; a killed daemon's card goes
stale after 5 s.

### 8.4 Files

On the Pi (`~/src/nexxhub`, source of truth):
```
vis/nexxvis.c                         modified
vis/build.sh                          new (gcc command)
vis/shaders/10-aurora.frag            beat accent
vis/shaders/20-spectral-ring.frag     beat accent
vis/shaders/30-spectrum-tunnel.frag   beat accent
vis/shaders/40-beat.frag              new
hub/nexxbeatd.py                      new daemon
hub/test_nexxbeatd.py                 new unit tests
hub/djl_sim.py                        new Pro DJ Link simulator (tests)
units/nexxbeatd.service               new
units/nexx-visualizer.service         add NV_BEAT_FILE / NV_CDJ_CARD env
install.sh                            new install/backup/rollback helper
```

Installed:
```
/usr/local/bin/nexxvis
/usr/local/share/nexxvis/shaders/*.frag
/usr/local/lib/nexxhub/nexxbeatd.py
/etc/systemd/system/nexxbeatd.service
/etc/systemd/system/nexx-visualizer.service  (env additions)
```

Local mirror (this Mac): `/Users/cxfxcxb/nexxxen/nexxhub/` (copy of the changed
source + tests) and this design in
`/Users/cxfxcxb/nexxxen/docs/superpowers/specs/`. The working directory is not
a git repo; no commit is required, but keep the copy for review/rollback.

### 8.5 `nexxbeatd.service`

```ini
[Unit]
Description=nexxxen Pro DJ Link beat daemon (OPUS-QUAD over Wi-Fi)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cxfxcxb
RuntimeDirectory=nexxbeat
RuntimeDirectoryMode=0755
WorkingDirectory=/home/cxfxcxb
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /usr/local/lib/nexxhub/nexxbeatd.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

No `Conflicts=` with `nexxhub` or the screen modes. `RuntimeDirectory`
creates `/run/nexxbeat` owned by `cxfxcxb`, so `nexxvis` (same user via
`PAMName=login`) can read it and the daemon needs no root. Ports 50000/50002
are unprivileged.

### 8.6 Build and deploy

`vis/build.sh`:
```sh
#!/bin/sh
set -eu
cd "$(dirname "$0")"
gcc -O2 -Wall -Wextra -o nexxvis nexxvis.c \
    -lEGL -lGLESv2 -lgbm -ldrm -lm -lpthread
```

`install.sh` (run with `sudo`, back up first):
0. **Sync the source tree to the live production baseline first**: copy the
   installed unit env (`NV_MODE=2560x1440@60`, `NV_SCALE=0.375`) and the live
   `10-aurora.frag` scale (`0.25`) into `~/src/nexxhub`, so installing the
   source cannot silently change the render resolution or GPU cost. The
   binaries already match.
1. Back up `/usr/local/bin/nexxvis` → `nexxvis.bak-YYYYMMDD-HHMM`, the
   installed service files, **and the whole
   `/usr/local/share/nexxvis/shaders/` directory**.
2. Install the binary, shaders (on rollback, also delete `40-beat.frag`),
   daemon, unit; `systemctl daemon-reload`.
3. `systemctl enable --now nexxbeatd`.
4. Restart the visualizer **only if it is the active screen mode**:
   `systemctl is-active --quiet nexx-visualizer && systemctl restart
   nexx-visualizer`. If Kodi/Artemis/RetroArch is active, leave it alone; the
   hub will start the new visualizer the next time it selects `vis`.
5. `--rollback` restores the binary, the shader directory (deleting
   `40-beat.frag`), and the service files, disables `nexxbeatd`, and restarts
   the visualizer only if it is active.

The user runs installs themselves if they prefer; NOPASSWD sudo is available.

### 8.7 Configuration knobs

In `/etc/nexxhub.json` the hub already has timeouts; leave it unchanged. The
new daemon/visualizer knobs are environment variables (defaults in code):

- `NB_OFFSET_MS` (0) — beat pulse offset, positive = later.
- `NB_STATUS_TIMEOUT_MS` (1500) — DJ state freshness.
- `NB_REHANDSHAKE_S` (3 / 30) — resend `sendCdj`.
- `NB_SIMULATE` (0) — accept the simulator on loopback only.
- `NV_BEAT_FILE` (`/run/nexxbeat/beat`).
- `NV_CDJ_CARD` (`/run/nexxbeat/cdj.rgba`).
- `NV_BEAT_LOG` (0) — once per second log `source bpm conf` for tuning.

### 8.8 Performance and thermal

- `nexxbeatd`: UDP parsing + a 5.86 Hz status tick + a 30 Hz file write +
  a ~2 Hz Pillow card render; expect < 3 % of one core, < 100 MB RSS.
- `nexxvis`: the extra flux/onset math is O(512) per frame; < 2 % extra.
- The new shader runs at 0.33 scale and must not exceed the current GPU load.
- The existing `cec_remote.py` CPU spin (§12) must be measured around; it is
  not caused by this project.

## 9. Security and authorization

- The daemon only listens on the user's own LAN and sends the documented
  rekordbox-style handshake to the user's own OPUS-QUAD. It impersonates a
  rekordbox client, which is how third-party Pro DJ Link software joins; no
  device settings are changed.
- No cloud, no audio upload, no fingerprinting, no external requests.
- State files are world-readable only under `/run/nexxbeat`; no secrets.

## 10. Testing

**Unit (Python `unittest`, on the Pi or the Mac).**
- Packet builders: keep-alive and `sendCdj` match the reference bytes.
- Status parser: fixtures from the 2026-11-22 capture (decks 9–12) →
  BPM/pitch/flags/track ID/counter; malformed lengths are rejected.
- Counter unwrap/reset: wrap at 65535, missed packets (delta > 1), track
  change reset.
- Phase estimator: synthetic arrivals with uniform jitter over one status
  interval → phase error < 20 ms after 16 beats.
- Deck selection: master beats playing; on-air fallback; idle.
- Card: renders a valid RGBA file; missing art falls back to the glyph;
  removes the file on idle.
- State file: atomic (no partial reads under a reader loop).
- Card liveness: on a steady track (>10 s) the card stays visible; a killed
  daemon hides it after 5 s; a pause removes it after 5 s without pulsing.
- Deck switch while deck B loads a track: the card keeps deck A's art.
- Install while Kodi is active: Kodi is not stopped; rollback restores the
  shader directory.

**Simulator (`djl_sim.py`).** Listen on 50000 for the daemon's keep-alive;
reply with `0x10`; then unicast `0x0a` status packets with a synthetic beat
counter at a configured BPM/pitch, flags, track IDs, and jitter; optionally
send `0x56` art. Run on loopback with `NB_SIMULATE=1` and assert that the
daemon publishes the right BPM/deck/phase.

**PipeWire.** Generate a click WAV (e.g. 120 BPM) and `pw-play` it to
`speakereq2x2`; `NV_BEAT_LOG=1` should show `source=audio bpm≈120` and the
pulse should be steady. Test with real Spotify/AirPlay music too.

**Device.** OPUS-QUAD playing on Wi-Fi: the card appears, the pulse tracks
the music, deck switches follow. A 5-minute capture while mixing validates
track changes, tempo changes and counter resets (log the status stream; keep
it in `nexxbeat-recon/`).

**Regression.** Launcher menu (gamepad/TV remote), nowplaying card, Kodi/
Artemis/RetroArch switching, source-switch, reboot. Compare journal errors.

## 11. Acceptance criteria

1. OPUS-QUAD playing over Wi-Fi: within ~5 s the CDJ card shows deck/BPM/art
   and the visuals pulse; after ~10 s the pulse error is ≤ 50 ms (optional
   `NB_OFFSET_MS` tuning).
1b. A steady track keeps the card visible (heartbeat); a pause stops the DJ
   pulses while the card may remain for the 5 s hold.
2. OPUS-QUAD stopped/off: no DJ pulses; the card fades and disappears.
3. Spotify/AirPlay/Moonlight playing: audio-detected beats pulse; the
   now-playing card still works.
4. Silence: no bogus pulses; `iBeat.w` low.
5. Deck switch (master/on-air) follows within 1 s; tempo change re-locks
   within ~2 s.
6. The launcher menu, mode switching, source-switch and audio routing are
   unchanged. Installing/rolling back while Kodi/Artemis/RetroArch is active
   does not stop that session.
7. After reboot the daemon re-discovers the OPUS-QUAD with no manual steps.
8. `nexxbeatd` < 3 % CPU; visualizer increase < 2 %; no throttling.
9. Rollback restores the previous visualizer and stops the daemon.

## 12. Known pre-existing issue (out of scope)

`cec_remote.py` (system service `nexx-cec-remote.service`) is at ~100 % CPU on
one core. It is unrelated to this project, but it eats headroom and heats the
Pi. Fix separately (likely a busy loop on the uinput/CEC fd); do not fold it
into this change.

## 13. v1.1 and deferred items

- **Titles via the USB library.** Match the live PSSI (`0x56` subtype `0x0a`)
  to the USB's `PIONEER` analysis files with SHA-1 (the `OpusProvider`
  approach), then read title/artist/album from the classic DeviceSQL DB (or
  `exportLibrary.db` with a key). Needs the USB's `PIONEER` folder copied to
  the Pi (or the stick plugged in) for a feasibility check. The Pi has no
  Java/pip; implement a minimal pure-Python PDB/ANLZ parser, or install
  `python3-pip`/`pyrekordbox` if the user approves. This is a separate
  sub-project; do not block v1 on it.
- **Optical audio capture** (DSP `SDATA_OUT` breakout or USB S/PDIF receiver)
  for spectrum from the DJ source; deferred.
- **Shazam/fingerprinting**: rejected (see §7.3).

## 14. What is left to the builder

- Validate the beat-counter semantics across track loads, pauses, deck
  switches and tempo changes with a 5-minute capture; adjust the reset/jump
  thresholds.
- Tune the min-residual window/percentile, the period EMA, and the default
  offset; measure the actual pulse error and report it.
- Implement and tune the PipeWire onset/BPM detector; choose the flux band and
  thresholds on real music, not just clicks.
- Finish the card visual (fonts/colors/art crop) to match `nowplaying.py`.
- Tune the new shader's cost at 2560×1440 / 0.33 scale.
- Decide whether to show the raw track ID on the card in v1 (default: no).
- Measure CPU/temperature with `cec_remote.py` running; report the delta.
- Sync the source tree to the live production values before editing (see §5).
- Investigate the CDJ-style keep-alive / absolute-position mode: can it give a
  direct playhead **while album art still works** (one client, or two
  identities)? If yes, compare accuracy/complexity with the counter+PLL;
  otherwise keep the counter. Do not block v1.
- Implement the card heartbeat, per-deck art cache and `playing` semantics per
  §8.2/§8.3, and the install/rollback safety per §8.6.

## 15. Calls made during review

These were settled by the builder (not the user) because a sensible default
exists; flag them if you disagree:

1. **Baseline = live production files.** The source tree is stale (unit env
   and aurora shader scale); sync it to the installed values before building.
   The live `2560x1440@60` / `0.375` / `0.25` settings are treated as
   intentional.
2. **Card liveness = daemon heartbeat.** Rewrite/touch `cdj.rgba` every 2 s
   while the selected deck plays; the visualizer keeps its <5 s mtime rule.
3. **`playing` = the deck's own status flag.** The 5 s post-stop hold keeps
   the deck/card selected but does not keep the beat clock running; pauses
   never invent beats.
4. **Per-deck art cache.** Keyed by (deck, track ID), so a non-selected deck's
   load cannot overwrite the card.
5. **Install does not disturb other screen modes.** Restart the visualizer
   only if it is active; rollback backs up/restores the shader directory.
6. **Counter + PLL over the CDJ keep-alive mode.** The counter preserves album
   art (the CDJ mode reportedly loses metadata/PSSI) and is accurate enough
   for a screensaver; the CDJ mode remains a builder validation, not the v1
   core.

---

## Appendix A — Protocol facts (verified 2026-11-22)

- Keep-alive and `sendCdj` layouts: §8.2; reference
  `github.com/kyleawayan/opus-quad-pro-dj-link-analysis` (`pro-dj-link.js`).
- Status packet: 293 bytes; type `0x0a`; standard CDJ layout with the device
  name at `0x0b`; BPM ×100 at `0x92`; pitch at `0x8d` (centre `0x100000`);
  flags at `0x89`; track ID at `0x2c`; beat counter at `0xa2`.
- 2026-11-22 spike (90 s): 2,185 packets — 88 keep-alives, 1,938 status
  (527 for deck 9), 140 metadata (`0x56`), 1 `0x10`, 18 `0x30`. Deck 9:
  174.00 BPM, pitch +1.19 %, playing/master/on-air, counter 297→560 =
  263 increments in 89.7 s = 175.98 BPM. Decks 11/12 stopped: counter
  constant. Status rate 5.86 Hz; increment intervals 203–499 ms (mean 341).
- Metadata: subtype 2 = JFIF album art; subtype `0x0a` = PSSI; no title/artist
  strings in any packet. Reference: djl-analysis.deepsymmetry.org,
  BLT 8.0 Opus Quad guide.

## Appendix B — Why the hidden counter is the right clock

The published analyses say the OPUS-QUAD has no beat packets and no precise
playhead, and Beat Link Trigger accepts ~200 ms tempo-sync error. The status
packet nevertheless carries a 16-bit beat counter that increments once per
beat and matches BPM × pitch exactly. The status rate is ~2× the beat rate,
so each beat is sampled within ~171 ms; over many beats the sampling phase
drifts, and the minimum observed residual estimates the true beat phase. That
turns a documented "impossible" into a usable ≤ 50 ms pulse with no audio
capture. If a firmware update removes the counter, the BPM-only clock remains
(less precise) and the audio path is the fallback.

---

## Appendix C — verification record (2026-11-22)

- **Unit tests (Pi):** `python3 -m unittest test_djl_protocol test_beatclock test_card test_nexxbeatd` → **53 pass**.
- **C tests:** `test_beatstate` → ok. `test_beatdetect` → clicks 120.00 BPM, conf 1.00, prediction error 0.0 ms; noise conf 0.00.
- **End-to-end simulator:** `python3 test_integration.py` → **PASS** (DJ playing → pause → 180 BPM relock ≤2 s → track jump 1217→1218 → idle).
- **Live OPUS-QUAD (<deck-ip>):** deck 1 playing track 1089 → state line `2 1 173.91 0.8487 0.84 1 … 1089`; `cdj.rgba` present and the visualizer logged `CDJ card shown`.
- **Audio fallback:** 120 BPM click track → `source=1 bpm 121.8–123.7 conf 0.31–0.50`; silence/noise → `source=0`.
- **Install/rollback:** install → `nexxbeatd` active, `NV_BEAT_FILE`/`NV_CDJ_CARD` in the unit; rollback → original binary (`sha256 869a5a97…`) + the original 3 shaders, daemon and unit removed; reinstall → all 5 shaders, daemon re-joined the OPUS.
- **Pending:** on-TV beat-offset tuning, a 5-minute mix capture, and reboot/regression confirmation (need the user).
- **vizz.fm mesh-grid:** preset `config-1740884813034-660` resolves to the built-in **mesh-grid** visualizer, variant 7. The site's bundle is marked "not open source … reverse engineering is prohibited", so `50-mesh-grid.frag` is an **original** raymarched wireframe implementation informed by the observed behavior, not copied GLSL.

### Performance (measured 2026-11-22, live OPUS-QUAD, active deck switching)

`nexxbeatd` 3.00 % of one core (select()-based loop; card fonts/shadow cached;
18.3 ms per 1180×300 render), `nexxvis` 8.1 % total, SoC 70.6 °C,
`get_throttled=0x0`. The pre-existing `cec_remote.py` still pins one core.

### Reboot regression (2026-11-22 00:14)

Clean reboot (~22 s). `nexxbeatd` active+enabled, `nexx-visualizer` active,
`/run/nexxbeat` created, daemon re-joined the OPUS-QUAD at <deck-ip> and
saw all four decks, all five shaders loaded, state idle (no deck playing),
69.1 °C, `get_throttled=0x0`. No manual steps.
