#!/usr/bin/env python3
"""Merge the nexxhub Artemis stream profile into Artemis.conf (run as the Artemis user before it starts).

Only applies when the profile is newer than the last apply, so settings changed later in the Artemis UI
are kept until the profile itself is edited again. Artemis.conf is a QSettings INI; only keys in
[General] are touched and everything else (pairing certs, hosts, ...) is preserved byte for byte.
"""
import os
import sys
from pathlib import Path

PROFILE = Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/nexxhub/artemis-settings.ini")
CONF = Path.home() / ".config" / "Artemis Desktop Project" / "Artemis.conf"
STAMP = CONF.with_name(".nexxhub-settings-applied")


def read_profile() -> dict:
    vals, section = {}, None
    for line in PROFILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
            continue
        if section == "[General]" and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def main() -> int:
    if not PROFILE.exists():
        return 0
    if STAMP.exists() and STAMP.stat().st_mtime >= PROFILE.stat().st_mtime:
        return 0
    vals = read_profile()
    lines = CONF.read_text().split("\n") if CONF.exists() else []
    if "[General]" not in lines:
        lines = ["[General]", ""] + lines
    # 1) replace existing keys inside [General]
    out, in_general, done, general_end = [], False, set(), None
    for line in lines:
        if line.startswith("["):
            if in_general:
                general_end = len(out)
            in_general = line == "[General]"
            out.append(line)
            continue
        if in_general and "=" in line:
            k = line.split("=", 1)[0]
            if k in vals:
                out.append(f"{k}={vals[k]}")
                done.add(k)
                continue
        out.append(line)
    if in_general:
        general_end = len(out)
    # 2) add missing keys at the end of [General], before its trailing blank lines
    missing = [f"{k}={v}" for k, v in vals.items() if k not in done]
    if missing:
        pos = general_end
        while pos > 0 and out[pos - 1] == "":
            pos -= 1
        out[pos:pos] = missing
    CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_suffix(".nexxhub-tmp")
    tmp.write_text("\n".join(out))
    os.replace(tmp, CONF)
    STAMP.touch()
    print(f"applied {len(vals)} Artemis settings from {PROFILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
