#!/bin/sh
# nexxhub beat-reactive install / rollback helper.
# Usage: sudo ./install.sh [--dry-run | --rollback]
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN=/usr/local/bin/nexxvis
SHADERS=/usr/local/share/nexxvis/shaders
HUBLIB=/usr/local/lib/nexxhub
UNITDIR=/etc/systemd/system
BACKUPS=/var/backups/nexxxen
LAST="$BACKUPS/nexxvis-last"

DRY=0
MODE=install
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --rollback) MODE=rollback ;;
        *) echo "usage: $0 [--dry-run | --rollback]" >&2; exit 2 ;;
    esac
done

run() {
    if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi
}
say() { echo "install: $*"; }

# ---------------------------------------------------------------- rollback
if [ "$MODE" = rollback ]; then
    [ -f "$LAST" ] || { echo "install: no backup recorded ($LAST)" >&2; exit 1; }
    BK=$(cat "$LAST")
    [ -d "$BK" ] || { echo "install: backup $BK is missing" >&2; exit 1; }
    say "rollback from $BK"
    run systemctl disable --now nexxbeatd || true
    run systemctl disable --now nexx-genome || true
    run rm -f "$UNITDIR/nexx-genome.service"

    run install -m 755 "$BK/nexxvis" "$BIN"
    run mkdir -p "$SHADERS"
    for f in "$SHADERS"/*.frag; do
        [ -e "$f" ] || continue
        [ -e "$BK/shaders/$(basename "$f")" ] || run rm -f "$f"
    done
    run cp -a "$BK/shaders/." "$SHADERS/"
    run cp -a "$BK/units/nexx-visualizer.service" "$UNITDIR/"
    if [ -f "$BK/units/nexxbeatd.service" ]; then
        run cp -a "$BK/units/nexxbeatd.service" "$UNITDIR/"
    else
        run rm -f "$UNITDIR/nexxbeatd.service"
    fi
    run systemctl daemon-reload
    if systemctl is-active --quiet nexx-visualizer; then
        run systemctl restart nexx-visualizer
    fi
    say "rollback complete"
    exit 0
fi

# ---------------------------------------------------------------- baseline
grep -q 'Environment=NV_MODE=2560x1440@60' "$SRC/units/nexx-visualizer.service" \
    || { echo "install: source unit lost the live NV_MODE baseline" >&2; exit 1; }
grep -q 'Environment=NV_SCALE=0.65' "$SRC/units/nexx-visualizer.service" \
    || { echo "install: source unit lost the live NV_SCALE baseline" >&2; exit 1; }
grep -q 'nv:scale=0.25' "$SRC/vis/shaders/10-aurora.frag" \
    || { echo "install: source 10-aurora lost the live nv:scale=0.25 baseline" >&2; exit 1; }

TS=$(date +%Y%m%d-%H%M%S)
BK="$BACKUPS/nexxvis-$TS"
say "backup $BK"
run mkdir -p "$BK/units" "$BK/shaders"
run cp -a "$BIN" "$BK/nexxvis"
run cp -a "$SHADERS/." "$BK/shaders/"
run cp -a "$UNITDIR/nexx-visualizer.service" "$BK/units/"
if [ -f "$UNITDIR/nexxbeatd.service" ]; then
    run cp -a "$UNITDIR/nexxbeatd.service" "$BK/units/"
fi
if [ "$DRY" = 1 ]; then
    echo "+ printf '%s\\n' '$BK' > '$LAST'"
else
    mkdir -p "$BACKUPS"
    printf '%s\n' "$BK" > "$LAST"
fi

# ---------------------------------------------------------------- build
say "build"
run sh -c "cd '$SRC/vis' && ./build.sh"

# ---------------------------------------------------------------- install
say "install binary, shaders, daemon, units"
run install -m 755 "$SRC/vis/nexxvis" "$BIN"
run mkdir -p "$SHADERS"
run cp -a "$SRC/vis/shaders/." "$SHADERS/"
run install -d "$HUBLIB"
run install -m 644 "$SRC/hub/nexxbeatd.py" "$SRC/hub/djl_protocol.py" \
    "$SRC/hub/beatclock.py" "$SRC/hub/card.py" "$SRC/hub/nowplaying.py" \
    "$SRC/hub/evolve.py" "$SRC/hub/embed.js" "$HUBLIB/"
run install -m 644 "$SRC/units/nexxbeatd.service" \
    "$SRC/units/nexx-visualizer.service" "$SRC/units/nexx-genome.service" "$UNITDIR/"
run systemctl daemon-reload
run systemctl enable nexxbeatd
run systemctl restart nexxbeatd
run systemctl enable nexx-genome
run systemctl restart nexx-genome
if systemctl is-active --quiet nexx-visualizer; then
    run systemctl restart nexx-visualizer
fi
say "done"
