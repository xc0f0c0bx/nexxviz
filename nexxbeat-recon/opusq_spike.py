#!/usr/bin/env python3
"""Throwaway OPUS-QUAD Pro DJ Link spike.

Sends the documented rekordbox-style keep-alive + sendCdj handshake, then logs
every packet the unit returns on UDP 50002 for a bounded time.

Run on the Pi: python3 opusq_spike.py [seconds] [unit-ip]
"""
import binascii
import os
import select
import socket
import sys
import time

HDR = bytes([0x51, 0x73, 0x70, 0x74, 0x31, 0x57, 0x6D, 0x4A, 0x4F, 0x4C])
NAME = "rekordbox"
CLIENT = "nexxxen"
IP = os.environ.get("NB_PI_IP", "127.0.0.1")
MAC = bytes.fromhex(os.environ.get("NB_PI_MAC", "aabbccddeeff"))
BROADCAST = os.environ.get("NB_BROADCAST", "255.255.255.255")
UNIT_IP = (sys.argv[2] if len(sys.argv) > 2
           else os.environ.get("NB_DECK_IP", "255.255.255.255"))
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 90
LOG = "/tmp/opusq_spike.log"


def devname(s: str, n: int = 20) -> bytes:
    return s.encode()[:n].ljust(n, b"\0")


def weird(s: str) -> bytes:
    out = bytearray(255)
    for i, ch in enumerate(s.encode()):
        if 2 * i < 255:
            out[2 * i] = ch
    return bytes(out)


def keepalive() -> bytes:
    return (HDR + b"\x06\x00" + devname(NAME)
            + bytes([0x01, 0x03, 0x00, 0x36, 0x17, 0x01])
            + MAC + socket.inet_aton(IP)
            + bytes([0x04, 0x01, 0x00, 0x00, 0x04, 0x08]))


def send_cdj() -> bytes:
    return (HDR + b"\x11" + devname(NAME)
            + bytes([0x01, 0x01, 0x17, 0x01, 0x04, 0x17, 0x01, 0x00, 0x00, 0x00])
            + weird(CLIENT))


def u16(b, o):
    return (b[o] << 8) | b[o + 1] if len(b) > o + 1 else None


def u32(b, o):
    return int.from_bytes(b[o:o + 4], "big") if len(b) > o + 3 else None


def describe(b: bytes) -> str:
    t = b[10] if len(b) > 10 else -1
    parts = [f"type=0x{t:02x}"]
    if t == 0x0A:
        # classic CDJ status fields, best effort
        parts += [
            f"deck@0x21={b[0x21] if len(b) > 0x21 else None}",
            f"tracklen@0x28={u32(b, 0x28)}",
            f"bpm@0x2c={u16(b, 0x2c)}",
            f"beatbar@0x2e={b[0x2e] if len(b) > 0x2e else None}",
            f"beat@0x30={b[0x30] if len(b) > 0x30 else None}",
            f"state@0x37={b[0x37] if len(b) > 0x37 else None}",
            f"pos@0x7b={u32(b, 0x7B)}",
        ]
        # scan plausible BPM values (x100) and 4-byte position candidates
        cand = [(o, u16(b, o)) for o in range(0x0B, min(len(b) - 1, 0xC0))]
        cand = [(o, v) for o, v in cand if 6000 <= v <= 19000]
        parts.append("bpm_candidates=" + ",".join(f"0x{o:02x}:{v}" for o, v in cand[:8]))
    elif t == 0x56:
        parts += [f"deck@0x21={b[0x21] if len(b) > 0x21 else None}",
                  f"subtype@0x25={b[0x25] if len(b) > 0x25 else None}",
                  f"trackId@0x28={u32(b, 0x28)}",
                  f"idx@0x31={b[0x31] if len(b) > 0x31 else None}",
                  f"count@0x33={b[0x33] if len(b) > 0x33 else None}"]
    elif t == 0x10:
        parts += [f"name={b[11:31].rstrip(bytes(1)).decode('ascii', 'replace')}",
                  f"tail={b[31:40].hex()}"]
    return " ".join(parts)


def main() -> None:
    ann = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ann.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ann.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    ann.bind(("0.0.0.0", 50000))
    st = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    st.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    st.bind(("0.0.0.0", 50002))

    end = time.monotonic() + DURATION
    next_ka = 0.0
    next_cdj = 0.0
    opus_ip = None
    counts = {}
    first_status = None
    n = 0
    with open(LOG, "w", buffering=1) as out:
        out.write(f"# spike start {time.time():.3f} unit={UNIT_IP} ip={IP} mac={MAC.hex()}\n")
        while time.monotonic() < end:
            now = time.monotonic()
            if now >= next_ka:
                ann.sendto(keepalive(), (BROADCAST, 50000))
                next_ka = now + 2.0
            if now >= next_cdj:
                target = opus_ip or UNIT_IP
                st.sendto(send_cdj(), (target, 50002))
                next_cdj = now + 10.0
                out.write(f"# sent sendCdj -> {target}:50002 at {time.time():.3f}\n")
            ready, _, _ = select.select([ann, st], [], [], 0.5)
            for s in ready:
                try:
                    data, addr = s.recvfrom(8192)
                except OSError:
                    continue
                n += 1
                t = data[10] if len(data) > 10 else -1
                counts[t] = counts.get(t, 0) + 1
                if s is st and len(data) > 30 and data[:10] == HDR and t == 0x10:
                    if opus_ip is None:
                        opus_ip = addr[0]
                        next_cdj = 0.0
                        out.write(f"# OPUS detected at {opus_ip} (0x10 reply)\n")
                if t == 0x0A and first_status is None:
                    first_status = data
                out.write(f"{time.time():.3f} {addr[0]}:{addr[1]} -> :{s.getsockname()[1]} "
                          f"len={len(data)} {describe(data)}\n  {data[:512].hex()}\n")
        out.write(f"# spike end, {n} packets, types="
                  + ", ".join(f"0x{k:02x}:{v}" for k, v in sorted(counts.items())) + "\n")
    print(f"packets={n} opus_ip={opus_ip}")
    print("types=" + ", ".join(f"0x{k:02x}:{v}" for k, v in sorted(counts.items())))
    if first_status:
        b = first_status
        print("first status:", describe(b))
        print("status hex:", b.hex())
    else:
        print("no 0x0a status packet seen")


if __name__ == "__main__":
    main()
