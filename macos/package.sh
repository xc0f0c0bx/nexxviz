#!/bin/sh
# Build Nexxvis.app and wrap it in a distributable DMG with the usual
# Applications drop target.
set -eu
cd "$(dirname "$0")"

./build.sh

VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" \
    build/Nexxvis.app/Contents/Info.plist 2>/dev/null || echo 0.1.0)
STAGE="build/dmg"
DMG="build/Nexxvis-$VERSION.dmg"

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R build/Nexxvis.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "Nexxvis" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
hdiutil verify "$DMG" >/dev/null
codesign --verify --deep build/Nexxvis.app >/dev/null 2>&1 || true

echo "built $DMG"
