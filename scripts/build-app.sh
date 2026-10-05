#!/bin/bash
# Builds Notetaker.app (menu bar app + bundled Python pipeline) and installs it to ~/Applications.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

# Needs a macOS 15+ SDK (ScreenCaptureKit microphone capture). Older Xcodes lack it, so prefer
# Command Line Tools' swiftc when present. Plain swiftc avoids SwiftPM toolchain mix-ups.
SWIFTC=$(xcrun --find swiftc)
SDK=$(xcrun --show-sdk-path)
CLT=/Library/Developer/CommandLineTools
if [ -x "$CLT/usr/bin/swiftc" ] && [ -d "$CLT/SDKs/MacOSX.sdk" ]; then
  SWIFTC="$CLT/usr/bin/swiftc"; SDK="$CLT/SDKs/MacOSX.sdk"
fi
mkdir -p build
# CLT 26.x ships SwiftBridging in both module.modulemap and bridging.modulemap ("redefinition of
# module"); overlay the duplicate with an empty file instead of editing the system install.
EXTRA=()
DUP="$(dirname "$SWIFTC")/../include/swift/bridging.modulemap"
if [ -f "$DUP" ] && grep -q "module SwiftBridging" "$(dirname "$SWIFTC")/../include/swift/module.modulemap" 2>/dev/null; then
  DUP=$(cd "$(dirname "$DUP")" && pwd)/bridging.modulemap
  : > build/empty.modulemap
  cat > build/overlay.yaml <<YAML
{ "version": 0, "roots": [ { "type": "file", "name": "$DUP", "external-contents": "$ROOT/build/empty.modulemap" } ] }
YAML
  EXTRA=(-vfsoverlay build/overlay.yaml -Xcc -ivfsoverlay -Xcc build/overlay.yaml)
fi
"$SWIFTC" "${EXTRA[@]}" -O -parse-as-library -swift-version 5 -target arm64-apple-macos15.0 -sdk "$SDK" \
  app/Sources/Notetaker/*.swift -o build/Notetaker

APP="$ROOT/build/Notetaker.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/pipeline"
cp build/Notetaker "$APP/Contents/MacOS/Notetaker"
cp app/Info.plist "$APP/Contents/Info.plist"
rsync -a --exclude .venv --exclude __pycache__ --exclude uv.lock pipeline/ "$APP/Contents/Resources/pipeline/"
[ -f pipeline/uv.lock ] && cp pipeline/uv.lock "$APP/Contents/Resources/pipeline/"

codesign --force --sign - --identifier com.local.notetaker "$APP"

DEST="$HOME/Applications"
mkdir -p "$DEST"
pkill -x Notetaker 2>/dev/null || true
rm -rf "$DEST/Notetaker.app"
cp -R "$APP" "$DEST/"
echo "Installed $DEST/Notetaker.app"
