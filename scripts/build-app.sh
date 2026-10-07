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
"$SWIFTC" ${EXTRA[@]+"${EXTRA[@]}"} -O -parse-as-library -swift-version 5 -target arm64-apple-macos15.0 -sdk "$SDK" \
  app/Sources/Notetaker/*.swift -o build/Notetaker

APP="$ROOT/build/Notetaker.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/pipeline"
cp build/Notetaker "$APP/Contents/MacOS/Notetaker"
cp app/Info.plist "$APP/Contents/Info.plist"

# App icon: app/icon/icon_1024.png (regenerate with app/icon/make-icon.swift) → AppIcon.icns
ICONSET=build/AppIcon.iconset
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s app/icon/icon_1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) app/icon/icon_1024.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rsync -a --exclude .venv --exclude __pycache__ --exclude uv.lock pipeline/ "$APP/Contents/Resources/pipeline/"
[ -f pipeline/uv.lock ] && cp pipeline/uv.lock "$APP/Contents/Resources/pipeline/"

# Bundle uv (single binary, MIT/Apache-2.0) so the app runs on Macs without it; it fetches Python itself.
UV_BIN="$(command -v uv || echo "$HOME/.local/bin/uv")"
mkdir -p "$APP/Contents/Resources/bin"
cp "$UV_BIN" "$APP/Contents/Resources/bin/uv"
cp scripts/notetaker-bundled "$APP/Contents/Resources/notetaker"

# Sign with a stable self-signed identity if present, so macOS keeps Microphone / Screen & System Audio
# permissions across rebuilds. Create it once: Keychain Access › Certificate Assistant › Create a
# Certificate… › Name "Notetaker Local Signing", Identity Type "Self Signed Root", Type "Code Signing".
IDENTITY="${NOTETAKER_SIGN_IDENTITY:-Notetaker Local Signing}"
if security find-identity -p codesigning 2>/dev/null | grep -q "\"$IDENTITY\""; then
  codesign --force --sign "$IDENTITY" "$APP/Contents/Resources/bin/uv"
  codesign --force --sign "$IDENTITY" --identifier com.local.notetaker "$APP"
  echo "Signed with \"$IDENTITY\" (permissions persist across rebuilds)"
else
  codesign --force --sign - "$APP/Contents/Resources/bin/uv"
  codesign --force --sign - --identifier com.local.notetaker "$APP"
  echo "Ad-hoc signed: macOS will ask for permissions again after this rebuild (see README › Stable signing)"
fi

[ "${NO_INSTALL:-}" = 1 ] && { echo "Built $APP"; exit 0; }
DEST="$HOME/Applications"
mkdir -p "$DEST"
pkill -x Notetaker 2>/dev/null || true
rm -rf "$DEST/Notetaker.app"
cp -R "$APP" "$DEST/"
echo "Installed $DEST/Notetaker.app"
