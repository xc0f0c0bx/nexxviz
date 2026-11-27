"""Pro DJ Link packet layouts and parsers for the OPUS-QUAD.

Only the subset needed by nexxbeatd is implemented: the rekordbox-style
announce keep-alive, the sendCdj handshake, the 0x0a status packet and the
0x56 binary metadata packet.  See docs/superpowers/specs/
2026-11-22-nexxvis-beat-reactive-design.md §8.2 and the recon notes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = bytes.fromhex("5173707431576d4a4f4c")  # "Qspt1WmJOL"
ANNOUNCE_PORT = 50000
STATUS_PORT = 50002
OPUS_NAME = "OPUS-QUAD"

_PITCH_CENTRE = 0x100000


def _fixed_name(name: str, size: int = 20) -> bytes:
    return name.encode("ascii", "replace")[:size].ljust(size, b"\0")


def _ip_bytes(ip: str) -> bytes:
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError(f"bad IPv4 address: {ip!r}")
    return bytes(int(p) for p in parts)


def keepalive(mac: bytes, ip: str) -> bytes:
    """Build the 54-byte rekordbox announce/keep-alive packet."""
    if len(mac) != 6:
        raise ValueError("mac must be 6 bytes")
    return (
        HEADER
        + b"\x06\x00"
        + _fixed_name("rekordbox")
        + bytes([0x01, 0x03, 0x00, 0x36, 0x17, 0x01])
        + mac
        + _ip_bytes(ip)
        + bytes([0x04, 0x01, 0x00, 0x00, 0x04, 0x08])
    )


def weird_string(name: str) -> bytes:
    """The 255-byte "weird string": name bytes at even offsets, NULs between."""
    out = bytearray(255)
    for i, ch in enumerate(name.encode("ascii", "replace")[:127]):
        out[2 * i] = ch
    return bytes(out)


def send_cdj(client_name: str = "nexxxen") -> bytes:
    """Build the 296-byte sendCdj handshake packet."""
    return (
        HEADER
        + b"\x11"
        + _fixed_name("rekordbox")
        + bytes([0x01, 0x01, 0x17, 0x01, 0x04, 0x17, 0x01, 0x00, 0x00, 0x00])
        + weird_string(client_name)
    )


def translate_deck(n: int) -> int:
    """OPUS-QUAD deck 9..12 -> display 1..4; anything else -> 0."""
    return n - 8 if 9 <= n <= 12 else 0


def pitch_percent(raw: int) -> float:
    """Pitch in percent; centre 0x100000 = 0.0 %."""
    return (raw - _PITCH_CENTRE) / _PITCH_CENTRE * 100.0


@dataclass
class Status:
    deck: int
    deck_display: int
    bpm_raw: int
    pitch_raw: int
    bpm_eff: float
    playing: bool
    master: bool
    on_air: bool
    synced: bool
    beat_counter: int
    track_id: int
    firmware: str
    t_recv: float


@dataclass
class Metadata:
    deck: int
    subtype: int
    track_id: int
    index: int
    count: int
    payload: bytes


def parse_status(pkt: bytes, t_recv: float) -> Status | None:
    """Parse a 0x0a status packet; None for anything malformed."""
    if len(pkt) < 0xA8 or pkt[10] != 0x0A:
        return None
    deck = pkt[0x21]
    bpm_raw = struct.unpack_from(">H", pkt, 0x92)[0]
    pitch_raw = int.from_bytes(pkt[0x8D:0x90], "big")
    flags = pkt[0x89]
    bpm_eff = 0.0
    if bpm_raw not in (0, 0xFFFF):
        bpm_eff = bpm_raw / 100.0 * (1.0 + pitch_percent(pitch_raw) / 100.0)
    return Status(
        deck=deck,
        deck_display=translate_deck(deck),
        bpm_raw=bpm_raw,
        pitch_raw=pitch_raw,
        bpm_eff=bpm_eff,
        playing=bool(flags & 0x40),
        master=bool(flags & 0x20),
        on_air=bool(flags & 0x08),
        synced=bool(flags & 0x10),
        beat_counter=struct.unpack_from(">H", pkt, 0xA2)[0],
        track_id=struct.unpack_from(">I", pkt, 0x2C)[0],
        firmware=pkt[0x7C:0x80].decode("ascii", "replace"),
        t_recv=t_recv,
    )


def parse_metadata(pkt: bytes) -> Metadata | None:
    """Parse a 0x56 binary metadata packet (album art / PSSI)."""
    if len(pkt) < 0x34 or pkt[10] != 0x56:
        return None
    return Metadata(
        deck=pkt[0x21],
        subtype=pkt[0x25],
        track_id=struct.unpack_from(">I", pkt, 0x28)[0],
        index=pkt[0x31],
        count=pkt[0x33],
        payload=bytes(pkt[0x34:]),
    )


def is_opus_reply(pkt: bytes) -> bool:
    """True for the 0x10 reply that announces the OPUS-QUAD's address."""
    return (
        len(pkt) >= 0x1F
        and pkt[:10] == HEADER
        and pkt[10] == 0x10
        and pkt[0x0B:0x1F].rstrip(b"\0") == OPUS_NAME.encode("ascii")
    )
