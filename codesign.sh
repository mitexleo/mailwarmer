#!/usr/bin/env bash
set -euo pipefail
APP="dist/MailWarmer.app"
if [ ! -d "$APP" ]; then
    echo "Error: $APP not found. Run build_mac.sh first."
    exit 1
fi
echo "Ad-hoc signing $APP..."
codesign --deep --force --sign - "$APP"
echo "Verifying..."
codesign -dv --verbose=4 "$APP"
echo "Done."
