#!/bin/bash
# Packs plugin/ into build/notetaker.plugin (zip) for Cowork upload.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
rm -f build/notetaker.plugin
(cd plugin && zip -qr ../build/notetaker.plugin . -x '.DS_Store')
echo "build/notetaker.plugin"
