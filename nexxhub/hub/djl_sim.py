#!/usr/bin/env python3
"""OPUS-QUAD Pro DJ Link simulator for nexxbeatd integration tests.

Binds the announce and status ports, answers the daemon's keep-alive with the
0x10 announcement, waits for the 0x11 handshake, then unicasts 0x0a status
packets at ~5.86 Hz with a synthetic beat counter.  Optional pause, tempo
change, track change and album art exercise the daemon's re-anchoring.

Run this on a different host from the daemon (e.g. the Mac), with the daemon's
NB_BROADCAST_ADDR set to this host's IP so the keep-alive is unicast here.
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from djl_protocol import HEADER  # noqa: E402

STATUS_RATE = 5.86
ART_CHUNK = 512 - 0x34


def build_status(deck: int, bpm_raw: int, pitch_raw: int, counter: int,
                 track_id: int, playing: bool, master: bool = True,
                 on_air: bool = True) -> bytes:
    p = bytearray(293)
    p[:10] = HEADER
    p[10] = 0x0A
    p[0x0B:0x0B + len(b"OPUS-QUAD")] = b"OPUS-QUAD"
    p[0x21] = deck
    struct.pack_into(">H", p, 0x22, 257)
    p[0x28] = deck
    struct.pack_into(">I", p, 0x2C, track_id)
    p[0x7C:0x80] = b"1.30"
    flags = 0
    if master:
        flags |= 0x20
    if on_air:
        flags |= 0x08
    if playing:
        flags |= 0x40
    p[0x89] = flags | 0x04
    p[0x8D:0x90] = pitch_raw.to_bytes(3, "big")
    struct.pack_into(">H", p, 0x92, bpm_raw)
    struct.pack_into(">H", p, 0xA2, counter & 0xFFFF)
    return bytes(p)


def build_art_packets(deck: int, track_id: int, data: bytes) -> list[bytes]:
    count = max(1, math.ceil(len(data) / ART_CHUNK))
    out = []
    for index in range(count):
        payload = data[index * ART_CHUNK:(index + 1) * ART_CHUNK]
        p = bytearray(0x34 + len(payload))
        p[:10] = HEADER
        p[10] = 0x56
        p[0x21] = deck
        p[0x25] = 2  # JPEG
        struct.pack_into(">I", p, 0x28, track_id)
        p[0x31] = index
        p[0x33] = count
        p[0x34:] = payload
        out.append(bytes(p))
    return out


def announce_reply(deck: int) -> bytes:
    return HEADER + b"\x10" + b"OPUS-QUAD".ljust(20, b"\0") + bytes([1, 0, deck, 0, 0])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OPUS-QUAD Pro DJ Link simulator")
    ap.add_argument("--announce-port", type=int, default=50000)
    ap.add_argument("--status-port", type=int, default=50002)
    ap.add_argument("--bpm", type=float, default=176.0)
    ap.add_argument("--pitch", type=float, default=0.0, help="percent")
    ap.add_argument("--deck", type=int, default=9)
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--pause-after", type=float, default=None)
    ap.add_argument("--bpm-change-after", type=float, default=None)
    ap.add_argument("--bpm-change", type=float, default=180.0)
    ap.add_argument("--track-change-after", type=float, default=None)
    ap.add_argument("--track-id", type=int, default=1217)
    ap.add_argument("--art", type=Path, default=None)
    args = ap.parse_args(argv)

    ann = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ann.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ann.bind(("0.0.0.0", args.announce_port))
    sta = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sta.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sta.bind(("0.0.0.0", args.status_port))
    ann.setblocking(False)
    sta.setblocking(False)

    art = args.art.read_bytes() if args.art else None
    deck, bpm = args.deck, args.bpm
    pitch_raw = int(round(0x100000 * (1.0 + args.pitch / 100.0)))
    track_id = args.track_id
    playing = True
    bpm_changed = track_changed = art_sent = False
    counter_base = 297
    beat = 0.0
    t0 = None                    # session starts at the handshake
    last_tick = None
    launched = time.monotonic()
    next_status = 0.0
    peer = None  # daemon address for status/art unicast

    print(f"sim: announce {args.announce_port}, status {args.status_port}, "
          f"deck {deck - 8}, {bpm} BPM, pitch {args.pitch:+.2f} %", flush=True)
    try:
        while True:
            now = time.monotonic()
            if t0 is None:
                if now - launched > 30.0:
                    print("sim: no handshake within 30 s", flush=True)
                    break
                elapsed = 0.0
            else:
                elapsed = now - t0
                if elapsed >= args.duration:
                    break

            if (args.pause_after is not None and elapsed >= args.pause_after
                    and not bpm_changed):
                playing = False
            if (args.bpm_change_after is not None
                    and elapsed >= args.bpm_change_after and not bpm_changed):
                bpm = args.bpm_change
                playing = True
                bpm_changed = True
                print(f"sim: bpm -> {bpm}", flush=True)
            if (args.track_change_after is not None
                    and elapsed >= args.track_change_after and not track_changed):
                track_id += 1
                beat += 50.0          # counter jump -> daemon must re-anchor
                track_changed = True
                art_sent = False
                print(f"sim: track -> {track_id} (counter jump)", flush=True)

            # daemon keep-alives -> answer with 0x10
            while True:
                try:
                    pkt, addr = ann.recvfrom(4096)
                except BlockingIOError:
                    break
                if len(pkt) >= 11 and pkt[:10] == HEADER and pkt[10] == 0x06:
                    peer = addr
                    ann.sendto(announce_reply(deck), addr)
            # handshake on the status port -> start sending status
            while True:
                try:
                    pkt, addr = sta.recvfrom(4096)
                except BlockingIOError:
                    break
                if len(pkt) >= 11 and pkt[:10] == HEADER and pkt[10] == 0x11:
                    peer = addr
                    if t0 is None:
                        t0 = now
                        last_tick = now
                    print(f"sim: handshake from {addr[0]}:{addr[1]}", flush=True)
                    art_sent = False

            if peer is not None and t0 is not None and now >= next_status:
                dt = now - last_tick
                last_tick = now
                if playing:
                    beat += dt * bpm * (1.0 + args.pitch / 100.0) / 60.0
                counter = counter_base + int(beat)
                sta.sendto(build_status(
                    deck, int(round(bpm * 100)), pitch_raw, counter, track_id, playing
                ), peer)
                if art and not art_sent:
                    for p in build_art_packets(deck, track_id, art):
                        sta.sendto(p, peer)
                    art_sent = True
                next_status = now + 1.0 / STATUS_RATE
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        ann.close()
        sta.close()
    print("sim: done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
