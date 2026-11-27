#!/bin/sh
# Build Nexxvis.app from the Swift package.  The app bundle is what makes
# Screen Recording (system audio) permission stick to the app's identity.
set -eu
cd "$(dirname "$0")"

swift build -c release

APP="build/Nexxvis.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/shaders"
cp .build/release/Nexxvis "$APP/Contents/MacOS/Nexxvis"
cp ../nexxhub/vis/shaders/15-crop-genesis.frag "$APP/Contents/Resources/shaders/15-crop-genesis.frag"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleExecutable</key><string>Nexxvis</string>
    <key>CFBundleIdentifier</key><string>fm.nexxxen.nexxvis</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleName</key><string>Nexxvis</string>
    <key>CFBundleDisplayName</key><string>Nexxvis</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>Nexxvis falls back to the microphone when system audio is not permitted.</string>
    <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict>
</plist>
EOF

codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "built $APP"
