#!/usr/bin/env python3
"""nexxhub CEC remote bridge: Samsung TV remote -> keyboard events for Kodi and the launcher menu.

The Pi stays registered as CEC Audio System (logical address 5, set up by cec-volume.service, which
keeps handling the volume keys). This process opens the same adapter as a second, non-exclusive
follower, so both see every message:

  * <User Control Pressed> keys addressed to us become key presses on a uinput keyboard
    ("nexxhub CEC remote") - only while the visualizer/menu or Kodi own the screen, never into a
    game stream. The Samsung keeps Return/Back for itself, so a long press on OK (>= 0.6 s) is Back.
  * acts as a proper CEC source: answers <Set Stream Path> / <Request Active Source> for our
    physical address, and when Kodi starts sends <Image View On> + <Active Source> so the TV switches
    to the Pi and routes the remote to it.

Mode comes from /run/nexxhub/mode (written by nexxhub). Stdlib + python3-evdev, kernel CEC API.
"""
from __future__ import annotations

import fcntl
import os
import select
import struct
import sys
import time
from pathlib import Path

from evdev import UInput, ecodes as E

DEV = os.environ.get("CEC_DEVICE", "/dev/cec1")
MODE_FILE = Path("/run/nexxhub/mode")
ACTIVITY_FILE = Path("/run/nexxhub/remote-activity")
OUR_LA = 5
BROADCAST = 0xF
TV = 0x0

IMAGE_VIEW_ON = 0x04
USER_CONTROL_PRESSED = 0x44
USER_CONTROL_RELEASED = 0x45
ACTIVE_SOURCE = 0x82
REQUEST_ACTIVE_SOURCE = 0x85
SET_STREAM_PATH = 0x86
ROUTING_CHANGE = 0x80

LONG_PRESS_S = 0.6
KEY_MODES = {"vis", "kodi"}   # screens that take remote keys

# CEC UI command -> Linux key (Kodi's default keyboard map understands all of these)
KEYMAP = {
    0x01: E.KEY_UP, 0x02: E.KEY_DOWN, 0x03: E.KEY_LEFT, 0x04: E.KEY_RIGHT,
    0x09: E.KEY_HOME,          # root menu
    0x0A: E.KEY_C, 0x0B: E.KEY_C,   # setup / contents menu -> context menu
    0x0D: E.KEY_BACKSPACE,     # exit (if the TV ever forwards it)
    0x2B: E.KEY_ENTER,
    0x30: E.KEY_PAGEUP, 0x31: E.KEY_PAGEDOWN,
    0x35: E.KEY_I,             # display information
    0x44: E.KEY_PLAYPAUSE, 0x46: E.KEY_PLAYPAUSE, 0x61: E.KEY_PLAYPAUSE,
    0x45: E.KEY_X,             # stop
    0x48: E.KEY_R, 0x49: E.KEY_F,          # rewind / fast forward
    0x4B: E.KEY_DOT, 0x4C: E.KEY_COMMA,    # next / previous
    0x71: E.KEY_F1, 0x72: E.KEY_F2, 0x73: E.KEY_F3, 0x74: E.KEY_F4,   # blue red green yellow
}
for i in range(10):
    KEYMAP[0x20 + i] = getattr(E, f"KEY_{i}")
SELECT = 0x00

# --- kernel CEC API (linux/cec.h) ----------------------------------------------------------------
MSG_FMT = "<QQIIII16sBBBBBBBx"


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("a") << 8) | nr


CEC_ADAP_G_PHYS_ADDR = _ioc(2, 1, 2)
CEC_TRANSMIT = _ioc(3, 5, struct.calcsize(MSG_FMT))
CEC_RECEIVE = _ioc(3, 6, struct.calcsize(MSG_FMT))
CEC_S_MODE = _ioc(1, 9, 4)
MODE_INITIATOR_FOLLOWER = 0x01 | 0x10   # non-exclusive: cec-volume follows the same adapter


def pack_msg(frame: bytes, timeout_ms: int = 0) -> bytes:
    return struct.pack(MSG_FMT, 0, 0, len(frame), timeout_ms, 0, 0, frame.ljust(16, b"\0"),
                       0, 0, 0, 0, 0, 0, 0)


def unpack_msg(buf: bytes) -> bytes:
    f = struct.unpack(MSG_FMT, buf)
    return f[6][:f[2]]


def log(msg: str) -> None:
    print(msg, flush=True)


class Bridge:
    def __init__(self) -> None:
        self.fd = os.open(DEV, os.O_RDWR | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, CEC_S_MODE, struct.pack("<I", MODE_INITIATOR_FOLLOWER))
        self.ui = UInput({E.EV_KEY: sorted(set(KEYMAP.values()) | {E.KEY_ENTER, E.KEY_BACKSPACE})},
                         name="nexxhub CEC remote")
        self.ok_down_at: float | None = None
        self.ok_long_fired = False
        self.active = False
        self.last_mode = None

    # ------------------------------------------------------------------ CEC helpers
    def phys_addr(self) -> int:
        buf = bytearray(2)
        fcntl.ioctl(self.fd, CEC_ADAP_G_PHYS_ADDR, buf)
        return struct.unpack("<H", buf)[0]

    def tx(self, frame: bytes) -> None:
        try:
            fcntl.ioctl(self.fd, CEC_TRANSMIT, bytearray(pack_msg(frame)))
        except OSError as e:
            log(f"tx {frame.hex(' ')} failed: {e}")

    def announce(self, wake_tv: bool) -> None:
        pa = self.phys_addr()
        if pa == 0xFFFF:
            return
        if wake_tv:
            self.tx(bytes([(OUR_LA << 4) | TV, IMAGE_VIEW_ON]))
        self.tx(bytes([(OUR_LA << 4) | BROADCAST, ACTIVE_SOURCE, pa >> 8, pa & 0xFF]))
        self.active = True
        log(f"active source {pa >> 12}.{(pa >> 8) & 0xF}.{(pa >> 4) & 0xF}.{pa & 0xF}" + (" (+image view on)" if wake_tv else ""))

    # ------------------------------------------------------------------ keys
    def mode(self) -> str:
        try:
            return MODE_FILE.read_text().strip()
        except OSError:
            return ""

    def tap(self, key: int) -> None:
        if self.mode() not in KEY_MODES:
            return
        self.ui.write(E.EV_KEY, key, 1)
        self.ui.syn()
        self.ui.write(E.EV_KEY, key, 0)
        self.ui.syn()
        try:
            ACTIVITY_FILE.touch()
        except OSError:
            pass

    def on_pressed(self, code: int) -> None:
        if code == SELECT:
            if self.ok_down_at is None:            # first press; repeats while held are ignored
                self.ok_down_at = time.monotonic()
                self.ok_long_fired = False
            return
        key = KEYMAP.get(code)
        if key is not None:
            self.tap(key)
            log(f"key 0x{code:02x} -> {E.KEY[key]}")
        else:
            log(f"key 0x{code:02x} unmapped")

    def on_released(self) -> None:
        if self.ok_down_at is not None:
            if not self.ok_long_fired:
                self.tap(E.KEY_ENTER)
                log("key OK -> KEY_ENTER")
            self.ok_down_at = None

    def check_long_press(self) -> None:
        if self.ok_down_at is not None and not self.ok_long_fired and time.monotonic() - self.ok_down_at >= LONG_PRESS_S:
            self.ok_long_fired = True
            self.tap(E.KEY_BACKSPACE)
            log("key OK (long) -> KEY_BACKSPACE")

    # ------------------------------------------------------------------ main loop
    def handle(self, frame: bytes) -> None:
        if len(frame) < 2:
            return
        src, dst, op = frame[0] >> 4, frame[0] & 0xF, frame[1]
        if dst == OUR_LA and op == USER_CONTROL_PRESSED and len(frame) > 2:
            self.on_pressed(frame[2])
        elif dst == OUR_LA and op == USER_CONTROL_RELEASED:
            self.on_released()
        elif op == SET_STREAM_PATH and len(frame) >= 4:
            if (frame[2] << 8 | frame[3]) == self.phys_addr():
                self.announce(wake_tv=False)       # the TV selected our input
            else:
                self.active = False
        elif op == REQUEST_ACTIVE_SOURCE and self.active:
            self.announce(wake_tv=False)
        elif op == ACTIVE_SOURCE and src != OUR_LA:
            self.active = False                    # someone else (or the TV itself) took over
        elif op == ROUTING_CHANGE and len(frame) >= 6:
            if (frame[4] << 8 | frame[5]) != self.phys_addr():
                self.active = False

    def run(self) -> None:
        log(f"cec-remote on {DEV}, phys addr 0x{self.phys_addr():04x}")
        poller = select.poll()
        poller.register(self.fd, select.POLLIN | select.POLLPRI)
        while True:
            for _fd, _ev in poller.poll(100):
                while True:
                    buf = bytearray(pack_msg(b""))
                    try:
                        fcntl.ioctl(self.fd, CEC_RECEIVE, buf)
                    except BlockingIOError:
                        break
                    except OSError as e:
                        if e.errno == 11:          # EAGAIN: queue drained
                            break
                        log(f"receive failed: {e}")
                        if e.errno == 19:          # ENODEV: adapter gone, let systemd restart us
                            sys.exit(1)
                        time.sleep(1)
                        break
                    self.handle(unpack_msg(bytes(buf)))
            self.check_long_press()
            mode = self.mode()
            if mode != self.last_mode:
                if mode == "kodi":
                    self.announce(wake_tv=True)    # Kodi started: TV to the Pi, remote to us
                self.last_mode = mode


if __name__ == "__main__":
    Bridge().run()
