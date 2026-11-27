#!/usr/bin/env python3
"""End-to-end integration test: djl_sim.py (this Mac) <-> nexxbeatd (Pi).

Standalone (not collected by unittest): run it directly.

    python3 test_integration.py            # full run, ~45 s
    python3 test_integration.py --no-sim   # RED check: must fail to see source=2

The daemon and simulator use test ports; the Pi's production ports are not
touched.  The simulator is reached by pointing NB_BROADCAST_ADDR at this
machine, so no broadcast filtering is involved.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KNOWN_HOSTS = "/Users/cxfxcxb/nexxxen/dsp-tools/known_hosts_nexxxen"

SIM_ANNOUNCE = 60400
SIM_STATUS = 60402
RUN_DIR = "/tmp/nb-it"


def get_mac_ip() -> str:
    for iface in ("en0", "en1"):
        r = subprocess.run(["ipconfig", "getifaddr", iface],
                           capture_output=True, text=True)
        if r.stdout.strip():
            return r.stdout.strip()
    raise SystemExit("no LAN IP found on en0/en1")


def ssh(pi: str, cmd: str, timeout: float = 90.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
         "-o", "ConnectTimeout=8", pi, cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def parse_line(line: str):
    parts = line.split()
    if len(parts) != 8:
        return None
    try:
        return {
            "source": int(parts[0]), "deck": int(parts[1]), "bpm": float(parts[2]),
            "phase": float(parts[3]), "conf": float(parts[4]),
            "playing": int(parts[5]), "mono": float(parts[6]), "track": int(parts[7]),
        }
    except ValueError:
        return None


def find(samples, t0, t1, pred):
    for ts, st in samples:
        if st is not None and t0 <= ts - t0_global <= t1 and pred(st):
            return st
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", default="nexxxen")
    ap.add_argument("--bpm", type=float, default=176.0)
    ap.add_argument("--no-sim", action="store_true")
    ap.add_argument("--duration", type=float, default=32.0)
    args = ap.parse_args(argv)

    ip = get_mac_ip()
    sim = None
    failures: list[str] = []
    try:
        if not args.no_sim:
            sim = subprocess.Popen(
                [sys.executable, str(HERE / "djl_sim.py"),
                 "--announce-port", str(SIM_ANNOUNCE),
                 "--status-port", str(SIM_STATUS),
                 "--bpm", str(args.bpm), "--pitch", "0", "--deck", "9",
                 "--duration", str(args.duration),
                 "--pause-after", "6", "--bpm-change-after", "10",
                 "--bpm-change", "180", "--track-change-after", "15"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            time.sleep(0.5)

        ssh(args.pi, f"rm -rf {RUN_DIR}; rm -f {RUN_DIR}.pid")
        r = ssh(args.pi,
                f"cd ~/src/nexxhub/hub && "
                f"(NB_RUN_DIR={RUN_DIR} NB_ANNOUNCE_PORT={SIM_ANNOUNCE} "
                f"NB_STATUS_PORT={SIM_STATUS} NB_BROADCAST_ADDR={ip} "
                f"nohup python3 nexxbeatd.py </dev/null >/tmp/nb-it.log 2>&1 & "
                f"echo $! >{RUN_DIR}.pid)")
        if r.returncode != 0:
            raise SystemExit(f"daemon start failed: {r.stderr}")

        # One SSH connection collects a timestamped state line every 0.4 s.
        n = int((args.duration + 10) / 0.4)
        t_start = time.time()
        r = ssh(args.pi,
                f"for i in $(seq 1 {n}); do "
                f"echo \"$(date +%s.%N) $(cat {RUN_DIR}/beat 2>/dev/null)\"; "
                f"sleep 0.4; done", timeout=args.duration + 30)
        if r.returncode != 0:
            raise SystemExit(f"collection failed: {r.stderr}")

        samples = []
        for line in r.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                ts = float(parts[0])
            except ValueError:
                continue
            samples.append((ts, parse_line(parts[1])))
        samples = [s for s in samples if s[1] is not None]
        if not samples:
            raise SystemExit("no state lines collected")
        global t0_global
        t0_global = samples[0][0]

        def expect(name, t0, t1, pred):
            st = find(samples, t0, t1, pred)
            if st is None:
                failures.append(f"{name}: no matching line in {t0}..{t1}s")
            else:
                print(f"ok  t={t0}-{t1}s {name}: {st}")
            return st

        expect("DJ playing ~176", 0.0, 6.0,
               lambda s: s["source"] == 2 and s["deck"] == 1 and s["playing"] == 1
               and abs(s["bpm"] - args.bpm) < 0.6 and s["conf"] > 0.3)
        expect("paused -> playing 0", 7.0, 9.5,
               lambda s: s["source"] == 2 and s["playing"] == 0)
        expect("tempo 180 re-lock <=2 s", 12.0, 14.5,
               lambda s: s["playing"] == 1 and abs(s["bpm"] - 180.0) < 0.6
               and s["conf"] > 0.3)
        expect("track change re-anchored", 17.5, 20.0,
               lambda s: s["track"] == 1218 and abs(s["bpm"] - 180.0) < 0.6
               and s["conf"] > 0.3)
        expect("idle after simulator stops", args.duration + 5.0, args.duration + 10.0,
               lambda s: s["source"] == 0 and s["deck"] == 0)
    finally:
        ssh(args.pi, f"kill -TERM $(cat {RUN_DIR}.pid) 2>/dev/null || true; rm -f {RUN_DIR}.pid")
        if sim is not None:
            sim.terminate()
            try:
                sim.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sim.kill()

    if failures:
        print("\nFAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("\nPASS")
    return 0


t0_global = 0.0
if __name__ == "__main__":
    sys.exit(main())
