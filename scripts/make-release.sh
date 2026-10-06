#!/bin/bash
# Builds build/Notetaker.zip (the app) + build/notetaker.plugin for a GitHub release.
set -euo pipefail
cd "$(dirname "$0")/.."
NO_INSTALL=1 scripts/build-app.sh
rm -f build/Notetaker.zip
ditto -c -k --sequesterRsrc --keepParent build/Notetaker.app build/Notetaker.zip
scripts/package-plugin.sh >/dev/null
echo "build/Notetaker.zip ($(du -h build/Notetaker.zip | cut -f1)), build/notetaker.plugin"
