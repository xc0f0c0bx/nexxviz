#!/bin/sh
# Build the nexxhub-visualizer HiFiBerryOS extension .deb and a local apt repo.
# Run on the Pi from anywhere:  sh build_deb.sh [--install]
set -eu

SRC=${SRC:-$HOME/src/nexxhub}
PKG=nexxhub-visualizer
VER=0.5.34
ROOT=${ROOT:-/tmp/$PKG-$VER}
DEB=/tmp/${PKG}_${VER}_arm64.deb
REPO=${REPO:-/srv/nexxvis-repo}
INSTALL=0
[ "${1:-}" = "--install" ] && INSTALL=1

rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/local/bin" "$ROOT/usr/local/share/nexxvis" \
         "$ROOT/usr/local/lib/nexxhub" "$ROOT/etc/systemd/system" \
         "$ROOT/etc/nginx/hifiberry-api.d" "$ROOT/etc/configserver/conf.d"

install -m755 "$SRC/vis/nexxvis" "$ROOT/usr/local/bin/nexxvis"
cp -a "$SRC/vis/shaders" "$ROOT/usr/local/share/nexxvis/"
if [ -d /usr/local/share/nexxvis/tiles ]; then
    cp -a /usr/local/share/nexxvis/tiles "$ROOT/usr/local/share/nexxvis/"
fi
for f in nexxbeatd.py djl_protocol.py beatclock.py card.py evolve.py webui.py nowplaying.py embed.js template_prior.py story.py; do
    install -m644 "$SRC/hub/$f" "$ROOT/usr/local/lib/nexxhub/$f"
done
for u in nexxbeatd.service nexx-genome.service nexxvisualizer-web.service nexx-visualizer.service nexx-story.service; do
    install -m644 "$SRC/units/$u" "$ROOT/etc/systemd/system/$u"
done
install -m644 "$SRC/units/nexxvisualizer.nginx" \
    "$ROOT/etc/nginx/hifiberry-api.d/nexxvisualizer.nginx"
cat > "$ROOT/etc/configserver/conf.d/nexxvis.json" <<'EOF'
{"systemd": {"nexxbeatd": "all", "nexx-genome": "all", "nexxvisualizer-web": "all", "nexx-visualizer": "all"}}
EOF

cat > "$ROOT/DEBIAN/control" <<'EOF'
Package: nexxhub-visualizer
Version: 0.5.34
Architecture: arm64
Maintainer: nexxxen <cxfxcxb@localhost>
Depends: python3, python3-pil, nginx
Description: nexxxen beat-reactive GLSL visualizer
 A multi-shader screensaver for the HDMI TV. Pro DJ Link beats from the
 OPUS-QUAD over Wi-Fi, PipeWire onset detection as the fallback, album-art
 palette, a genetic algorithm for variation, and a shader selector in the
 HiFiBerry web UI at /visualizer/.
XB-Hifiberry-Extension: yes
XB-Extension-Name: nexxxen Visualizer
XB-Extension-Category: tool
XB-Extension-Needs-Reboot: no
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
install -d -o cxfxcxb -g cxfxcxb /var/lib/nexxhub
systemctl daemon-reload || true
systemctl enable nexxbeatd nexx-genome nexxvisualizer-web nexx-story >/dev/null 2>&1 || true
systemctl restart nexxbeatd nexx-genome nexxvisualizer-web nexx-story >/dev/null 2>&1 || true
if command -v nginx >/dev/null 2>&1; then
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
fi
systemctl is-active --quiet nexx-visualizer && systemctl restart nexx-visualizer || true
INDEX=/usr/share/hifiberry/webui/index.html
if [ -f "$INDEX" ] && ! grep -q "/visualizer/embed.js" "$INDEX"; then
    cp -a "$INDEX" "$INDEX.before-nexxvis" 2>/dev/null || true
    if grep -q "</body>" "$INDEX"; then
        sed -i 's#</body>#<script src="/visualizer/embed.js" defer></script></body>#' "$INDEX"
    else
        printf '\n<script src="/visualizer/embed.js" defer></script>\n' >> "$INDEX"
    fi
fi
exit 0
EOF
cat > "$ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
systemctl stop nexxbeatd nexx-genome nexxvisualizer-web nexx-story 2>/dev/null || true
systemctl disable nexxbeatd nexx-genome nexxvisualizer-web nexx-story 2>/dev/null || true
exit 0
EOF
cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload || true
if command -v nginx >/dev/null 2>&1; then
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$ROOT" "$DEB"
echo "built $DEB"

sudo mkdir -p "$REPO"
sudo cp "$DEB" "$REPO/"
sudo sh -c "cd '$REPO' && dpkg-scanpackages . /dev/null > Packages && gzip -9c Packages > Packages.gz"
echo "repo $REPO updated"

if ! sudo test -f /etc/apt/sources.list.d/nexxvis.list; then
    echo 'deb [trusted=yes] file:/srv/nexxvis-repo ./' | sudo tee /etc/apt/sources.list.d/nexxvis.list >/dev/null
    sudo apt-get update >/dev/null
fi

if [ "$INSTALL" = 1 ]; then
    sudo apt-get update >/dev/null
    sudo apt-get install -y "$PKG"
    dpkg -s "$PKG" | grep -E "^(Package|Version|XB-|Hifiberry|Extension-)" || true
fi
