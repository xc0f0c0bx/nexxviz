#!/usr/bin/env python3
"""nexxhub - decides what the TV (HDMI, tty1) shows on nexxxen.

Screen modes, each a systemd unit; the units Conflict= with each other so only one owns the display:
  vis        nexx-visualizer.service   GLSL audio visualizer (default, also hosts the launcher menu)
  artemis    nexx-artemis.service      Artemis game streaming client (Apollo on the PC)
  kodi       nexx-kodi.service         Kodi media center
  retroarch  nexx-retroarch.service    RetroArch emulators

Behaviour
  - boot / nothing running            -> visualizer
  - gamepad connects while visualizer -> launcher menu over the visualizer (PC Games, Kodi, RetroArch,
                                         Visualizer); d-pad/stick chooses, A opens, B or "Visualizer" hides,
                                         Xbox/Start shows it again
  - app quits by itself               -> visualizer, menu shown if a gamepad is connected
  - Xbox button held >= 2 s in an app -> app is closed, back to the menu
  - no gamepad connected for N min    -> app is closed, back to the plain visualizer
                                         (games: artemis/retroarch 20 min, kodi 200 min)

Config: /etc/nexxhub.json (optional) {"timeouts_min": {"artemis": 20, "retroarch": 20, "kodi": 200},
                                      "menu_autohide_s": 90, "guide_hold_s": 2.0}
Menu state for the visualizer: /run/nexxhub/menu  -> "<visible 0|1> <selected index>"
Now-playing card (title/artist/album/cover from AudioControl): /run/nexxhub/nowplaying.rgba (nowplaying.py)
Manual control: `nexxhub-ctl <vis|artemis|kodi|retroarch|menu>` writes to /run/nexxhub/cmd (FIFO).
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import evdev
from evdev import ecodes as E

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nowplaying import NowPlaying  # noqa: E402

RUN = Path("/run/nexxhub")
MENU_FILE = RUN / "menu"
NOWPLAYING_FILE = RUN / "nowplaying.rgba"
MODE_FILE = RUN / "mode"                       # current screen mode, read by cec_remote.py
REMOTE_ACTIVITY = RUN / "remote-activity"      # touched by cec_remote.py on every TV-remote key
REMOTE_NAME = "nexxhub CEC remote"             # uinput keyboard created by cec_remote.py
CMD_FIFO = RUN / "cmd"
CONFIG = Path("/etc/nexxhub.json")

UNITS = {
    "vis": "nexx-visualizer.service",
    "artemis": "nexx-artemis.service",
    "kodi": "nexx-kodi.service",
    "retroarch": "nexx-retroarch.service",
}
MENU = ["artemis", "kodi", "retroarch", "vis"]      # order of the tiles (make_tiles.py)

DEFAULTS = {
    "timeouts_min": {"artemis": 20, "retroarch": 20, "kodi": 200},
    "menu_autohide_s": 90,
    "guide_hold_s": 2.0,
}

GUIDE_KEYS = {E.BTN_MODE, E.KEY_HOMEPAGE}
OPEN_KEYS = GUIDE_KEYS | {E.BTN_START}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        user = json.loads(CONFIG.read_text())
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    except FileNotFoundError:
        pass
    except Exception as e:  # keep running on a broken config
        log(f"config error, using defaults: {e}")
    return cfg


def systemctl(*args: str) -> str:
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=20)
    return r.stdout.strip()


def active_mode() -> str | None:
    """Mode whose unit is active/activating (the units conflict, so at most one)."""
    names = list(UNITS)
    states = systemctl("is-active", *[UNITS[n] for n in names]).splitlines()
    for name, st in zip(names, states):
        if st in ("active", "activating", "reloading"):
            return name
    return None


def is_gamepad(dev: evdev.InputDevice) -> bool:
    keys = dev.capabilities().get(E.EV_KEY, [])
    return E.BTN_SOUTH in keys or E.BTN_GAMEPAD in keys


class Pad:
    def __init__(self, dev: evdev.InputDevice):
        self.dev = dev
        self.axis = {}
        for code in (E.ABS_X, E.ABS_Y):
            try:
                ai = dev.absinfo(code)
                self.axis[code] = (ai.min, ai.max)
            except Exception:
                pass
        self.stick_dir = 0

    def norm(self, code: int, value: int) -> float:
        lo, hi = self.axis.get(code, (-32768, 32767))
        if hi == lo:
            return 0.0
        return (value - lo) / (hi - lo) * 2.0 - 1.0


class Hub:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.pads: dict[str, Pad] = {}
        self.remote: evdev.InputDevice | None = None   # Samsung TV remote via HDMI-CEC (cec_remote.py)
        self.last_pad_seen = time.monotonic()
        self.menu_visible = False
        self.menu_sel = 0
        self.menu_touched = time.monotonic()
        self.guide_down_at: float | None = None
        self.mode: str | None = None
        self.expect_mode: str | None = None    # mode we just asked systemd for
        self.expect_until = 0.0
        self.mode_poll = 0.0
        self.scan_at = 0.0
        self.running = True
        RUN.mkdir(parents=True, exist_ok=True)
        os.chmod(RUN, 0o755)
        if not CMD_FIFO.exists():
            os.mkfifo(CMD_FIFO, 0o620)
        self.fifo = os.open(CMD_FIFO, os.O_RDONLY | os.O_NONBLOCK)
        self.fifo_keep = os.open(CMD_FIFO, os.O_WRONLY | os.O_NONBLOCK)   # keeps the FIFO from hitting EOF
        self.write_menu()

    # ---------------------------------------------------------------- menu
    def write_menu(self) -> None:
        tmp = MENU_FILE.with_suffix(".tmp")
        tmp.write_text(f"{1 if self.menu_visible else 0} {self.menu_sel}\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, MENU_FILE)

    def show_menu(self, sel: int | None = None) -> None:
        if sel is not None:
            self.menu_sel = sel
        self.menu_visible = True
        self.menu_touched = time.monotonic()
        self.write_menu()

    def hide_menu(self) -> None:
        if self.menu_visible:
            self.menu_visible = False
            self.write_menu()

    def move(self, d: int) -> None:
        self.menu_sel = (self.menu_sel + d) % len(MENU)
        self.menu_touched = time.monotonic()
        self.write_menu()

    # ---------------------------------------------------------------- modes
    def set_mode(self, mode: str | None) -> None:
        self.mode = mode
        try:
            tmp = MODE_FILE.with_suffix(".tmp")
            tmp.write_text(f"{mode or ''}\n")
            os.chmod(tmp, 0o644)
            os.replace(tmp, MODE_FILE)
        except OSError as e:
            log(f"cannot write {MODE_FILE}: {e}")

    def remote_idle_s(self) -> float:
        try:
            return max(0.0, time.time() - REMOTE_ACTIVITY.stat().st_mtime)
        except OSError:
            return float("inf")

    def switch(self, mode: str, menu: bool = False) -> None:
        log(f"switch -> {mode}")
        if mode != "vis":
            self.hide_menu()
            self.last_pad_seen = time.monotonic()
        subprocess.run(["systemctl", "start", "--no-block", UNITS[mode]], timeout=20)
        self.expect_mode = mode
        self.expect_until = time.monotonic() + 30
        self.set_mode(mode)
        if mode == "vis":
            if menu and self.pads:
                self.show_menu(0)
            else:
                self.hide_menu()

    def activate(self) -> None:
        target = MENU[self.menu_sel]
        if target == "vis":
            self.hide_menu()
        else:
            self.switch(target)

    # ---------------------------------------------------------------- input
    def scan_pads(self) -> None:
        paths = set(evdev.list_devices())
        if self.remote is not None and self.remote.path not in paths:
            log("TV remote bridge gone")
            try:
                self.remote.close()
            except Exception:
                pass
            self.remote = None
        for p in list(self.pads):
            if p not in paths:
                log(f"gamepad gone: {self.pads[p].dev.name}")
                try:
                    self.pads[p].dev.close()
                except Exception:
                    pass
                del self.pads[p]
        new = False
        known = set(self.pads) | ({self.remote.path} if self.remote is not None else set())
        for p in paths - known:
            try:
                dev = evdev.InputDevice(p)
            except Exception:
                continue
            if dev.name == REMOTE_NAME:
                self.remote = dev
                log(f"TV remote bridge found ({p})")
            elif is_gamepad(dev):
                self.pads[p] = Pad(dev)
                log(f"gamepad connected: {dev.name} ({p})")
                new = True
            else:
                dev.close()
        if new and self.mode == "vis" and not self.menu_visible:
            self.show_menu(0)

    def handle_event(self, pad: Pad, ev) -> None:
        now = time.monotonic()
        if ev.type == E.EV_KEY:
            if ev.code in GUIDE_KEYS:
                if ev.value == 1:
                    self.guide_down_at = now
                elif ev.value == 0:
                    self.guide_down_at = None
            if self.mode != "vis" or ev.value != 1:
                return
            if not self.menu_visible:
                if ev.code in OPEN_KEYS or ev.code == E.BTN_SOUTH:
                    self.show_menu()
                return
            if ev.code == E.BTN_SOUTH:
                self.activate()
            elif ev.code == E.BTN_EAST:
                self.hide_menu()
            elif ev.code in (E.BTN_DPAD_LEFT, E.BTN_TL):
                self.move(-1)
            elif ev.code in (E.BTN_DPAD_RIGHT, E.BTN_TR):
                self.move(1)
            self.menu_touched = now
        elif ev.type == E.EV_ABS and self.mode == "vis" and self.menu_visible:
            if ev.code == E.ABS_HAT0X and ev.value != 0:
                self.move(1 if ev.value > 0 else -1)
            elif ev.code == E.ABS_X:
                x = pad.norm(E.ABS_X, ev.value)
                d = 1 if x > 0.6 else (-1 if x < -0.6 else 0)
                if d != pad.stick_dir:
                    pad.stick_dir = d
                    if d:
                        self.move(d)

    def handle_remote(self, ev) -> None:
        """Samsung TV remote (keyboard events from cec_remote.py) drives the launcher menu."""
        if ev.type != E.EV_KEY or ev.value != 1 or self.mode != "vis":
            return
        if not self.menu_visible:
            self.show_menu()
            return
        if ev.code in (E.KEY_LEFT, E.KEY_UP):
            self.move(-1)
        elif ev.code in (E.KEY_RIGHT, E.KEY_DOWN):
            self.move(1)
        elif ev.code == E.KEY_ENTER:
            self.activate()
        elif ev.code == E.KEY_BACKSPACE:
            self.hide_menu()
        self.menu_touched = time.monotonic()

    def read_fifo(self) -> None:
        try:
            data = os.read(self.fifo, 4096).decode(errors="replace")
        except BlockingIOError:
            return
        for cmd in data.split():
            if cmd in UNITS:
                self.switch(cmd, menu=(cmd == "vis"))
            elif cmd == "menu":
                if self.mode != "vis":
                    self.switch("vis", menu=True)
                else:
                    self.show_menu(0)
            elif cmd == "reload":
                self.cfg = load_config()
                log(f"config reloaded: {self.cfg}")

    # ---------------------------------------------------------------- main loop
    def tick(self) -> None:
        now = time.monotonic()
        if now >= self.scan_at:
            self.scan_pads()
            self.scan_at = now + 1.0
        if self.pads:
            self.last_pad_seen = now

        if now >= self.mode_poll:
            self.mode_poll = now + 2.0
            actual = active_mode()
            if self.expect_mode and now < self.expect_until and actual != self.expect_mode:
                pass   # transition in progress
            else:
                self.expect_mode = None
                if actual is None:
                    # app quit by itself (or boot): back to the visualizer, menu if a pad is there
                    log(f"nothing on screen (was {self.mode}) -> visualizer")
                    self.switch("vis", menu=True)
                elif actual != self.mode:
                    log(f"mode changed outside the hub: {self.mode} -> {actual}")
                    first = self.mode is None
                    self.set_mode(actual)
                    if actual != "vis":
                        self.hide_menu()
                    elif first and self.pads:
                        self.show_menu(0)     # hub (re)started while a controller is connected

        if self.mode and self.mode != "vis":
            hold = self.cfg["guide_hold_s"]
            if self.guide_down_at is not None and now - self.guide_down_at >= hold:
                self.guide_down_at = None
                log(f"Xbox button held in {self.mode} -> menu")
                self.switch("vis", menu=True)
                return
            limit = float(self.cfg["timeouts_min"].get(self.mode, 20)) * 60.0
            # TV-remote keys count as activity (cec_remote only forwards them to the menu and Kodi)
            idle = min(now - self.last_pad_seen, self.remote_idle_s())
            if not self.pads and idle >= limit:
                log(f"no gamepad or remote for {limit / 60:.0f} min in {self.mode} -> visualizer")
                self.switch("vis", menu=False)
                return

        if self.mode == "vis" and self.menu_visible and now - self.menu_touched > self.cfg["menu_autohide_s"]:
            self.hide_menu()

    def run(self) -> None:
        log(f"nexxhub up, config {self.cfg}")
        NowPlaying(NOWPLAYING_FILE, log).start()
        while self.running:
            fds = {p.dev.fd: p for p in self.pads.values()}
            extra = [self.fifo] + ([self.remote.fd] if self.remote is not None else [])
            try:
                r, _, _ = select.select(list(fds) + extra, [], [], 0.25)
            except (OSError, ValueError):
                r = []
            for fd in r:
                if fd == self.fifo:
                    self.read_fifo()
                    continue
                if self.remote is not None and fd == self.remote.fd:
                    try:
                        for ev in self.remote.read():
                            self.handle_remote(ev)
                    except OSError:
                        self.scan_at = 0
                    continue
                pad = fds.get(fd)
                if not pad:
                    continue
                try:
                    for ev in pad.dev.read():
                        self.handle_event(pad, ev)
                except OSError:
                    self.scan_at = 0   # device vanished; rescan now
            self.tick()


def main() -> None:
    hub = Hub()

    def stop(signum, frame):
        hub.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    hub.run()
    hub.menu_visible = False
    hub.write_menu()


if __name__ == "__main__":
    sys.exit(main())
