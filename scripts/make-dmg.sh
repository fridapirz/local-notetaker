#!/bin/bash
# Builds build/Notetaker-<version>.dmg: Notetaker.app + Applications shortcut + install notes.
set -euo pipefail
cd "$(dirname "$0")/.."
NO_INSTALL=1 scripts/build-app.sh
VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" app/Info.plist)
STAGE=build/dmg
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R build/Notetaker.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp app/dmg/INSTALL.txt "$STAGE/Read me first.txt"
OUT="build/Notetaker-$VERSION.dmg"
rm -f "$OUT"
hdiutil create -volname "Notetaker" -srcfolder "$STAGE" -ov -format UDZO -quiet "$OUT"
rm -rf "$STAGE"
echo "$OUT ($(du -h "$OUT" | cut -f1))"
